# SPDX-License-Identifier: GPL-3.0-only
"""Exercise two real desktop launches inside the admitted private namespace."""
import contextlib
import ctypes
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import secrets
import struct
import subprocess
import sys
import time

NAME = 'Public native WebView project'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
PORT = 6805
STAGES = ('admission', 'display', 'bus', 'first_launch', 'seed_project', 'refresh_dashboard',
          'first_open', 'first_editor', 'first_close', 'second_launch', 'second_open',
          'second_editor', 'second_close', 'cleanup', 'complete')


def require(condition):
    if not condition:
        raise RuntimeError('native_webview_rejected')


def load(name):
    source = Path('/run/fixture') / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def await_value(check, seconds=18):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.12)
    raise TimeoutError('native_webview_not_ready')


def remote(method, target, data=None):
    connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=1)
    try:
        body = None if data is None else json.dumps(data).encode()
        connection.request(method, target, body, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read(65537)
        require(len(raw) <= 65536 and 200 <= response.status < 300)
        return json.loads(raw)
    finally:
        connection.close()


def available():
    try:
        return remote('GET', '/api/website?connectorId=fs-storage') is not None
    except (ConnectionError, TimeoutError):
        return False


def visible_windows(title):
    result = subprocess.run(['/usr/bin/xdotool', 'search', '--onlyvisible', '--name', '^' + re.escape(title) + '$'],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=False)
    if result.returncode == 1 and not result.stdout:
        return []
    require(result.returncode == 0 and len(result.stdout) <= 256)
    return [int(row) for row in result.stdout.splitlines() if row.isdigit()]


def desktop_action(atspi, label, app_process):
    def locate():
        require(app_process.poll() is None)
        queue = [atspi.get_desktop(0)]
        for visited in range(2500):
            if not queue:
                return None
            node = queue.pop()
            if node is None:
                continue
            try:
                if node.get_name() == label:
                    action = node.get_action_iface()
                    if action and action.get_n_actions():
                        return action
                count = node.get_child_count()
                require(0 <= count <= 1024)
                queue.extend(node.get_child_at_index(i) for i in range(count))
            except Exception as error:
                # The accessibility tree can replace a loading WebKit document.
                if type(error).__module__.startswith('gi.repository'):
                    continue
                raise
        raise RuntimeError('accessibility_tree_bound')
    require(await_value(locate).do_action(0))


def webkit_process():
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            command = (proc / 'cmdline').read_bytes().split(b'\0', 1)[0]
            if not command.endswith(b'/WebKitWebProcess'):
                continue
            with (proc / 'status').open() as stream:
                raw = stream.read(65537)
            require(len(raw) <= 65536)
            status = dict(row.split(':', 1) for row in raw.splitlines() if ':' in row)
            if status['Uid'].split() == [str(os.getuid())] * 4 and status['NoNewPrivs'].strip() == '1':
                return int(proc.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return None


def request_close(window):
    # Send the window manager's normal WM_DELETE_WINDOW client message.
    x = ctypes.CDLL('libX11.so.6')
    ptr, word = ctypes.c_void_p, ctypes.c_ulong
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XOpenDisplay.restype = ptr
    x.XInternAtom.argtypes = [ptr, ctypes.c_char_p, ctypes.c_int]
    x.XInternAtom.restype = word
    x.XSendEvent.argtypes = [ptr, word, ctypes.c_int, ctypes.c_long, ptr]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ptr]
    class ClientMessage(ctypes.Structure):
        _fields_ = [('type', ctypes.c_int), ('serial', word), ('send_event', ctypes.c_int),
            ('display', ptr), ('window', word), ('message_type', word), ('format', ctypes.c_int),
            ('data', ctypes.c_long * 5)]
    display = x.XOpenDisplay(None)
    require(display)
    try:
        event = (ctypes.c_long * 24)()
        message = ClientMessage.from_buffer(event)
        message.type, message.display, message.window, message.format = 33, display, window, 32
        message.message_type = x.XInternAtom(display, b'WM_PROTOCOLS', 0)
        message.data[0] = x.XInternAtom(display, b'WM_DELETE_WINDOW', 0)
        require(x.XSendEvent(display, window, 0, 0, ctypes.byref(event)) != 0)
        x.XFlush(display)
    finally:
        x.XCloseDisplay(display)


def main():
    stage = 'admission'
    state = dict(process_groups_started=0, process_groups_joined=0, desktop_launches=0,
        native_window_closes=0, original_project_reopened=False)
    actor = load('isolation_actor')
    life = load('lifecycle')
    # The admission actor uses the same original identity and view assertions.
    actor.admission()
    require(Path(__file__).resolve() == Path('/run/fixture/webview.py') and os.getuid() != 0
            and not any(k.startswith('WEBKIT_') for k in os.environ))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 << 20, 16 << 20))
    private = Path(os.environ['XDG_RUNTIME_DIR'])
    cookie = private / 'xauthority'
    address = private / 'session-bus'
    # Xauthority FamilyWild, display 87, no network listener and fresh private cookie.
    def field(data):
        return struct.pack('!H', len(data)) + data
    with cookie.open('xb') as output:
        output.write(struct.pack('!H', 65535) + field(b'') + field(b'87')
                     + field(b'MIT-MAGIC-COOKIE-1') + field(secrets.token_bytes(16)))
    os.environ.update(DISPLAY=':87', XAUTHORITY=str(cookie), DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(address),
        GDK_BACKEND='x11', GTK_A11Y='atspi', NO_AT_BRIDGE='0', LIBGL_ALWAYS_SOFTWARE='1', LANG='C.UTF-8')
    @contextlib.contextmanager
    def service(command):
        process, identity = life.start_group(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=os.environ['HOME'], env=os.environ.copy(), close_fds=True)
        state['process_groups_started'] += 1
        try:
            yield process
        finally:
            result = life.drain_group(process, identity)
            require(result['leader_joined'] and result['live_group_drained'])
            state['process_groups_joined'] += 1
    try:
        with contextlib.ExitStack() as stack:
            stage = 'display'
            stack.enter_context(service(['/usr/bin/Xvfb', ':87', '-screen', '0', '1280x800x24', '-nolisten', 'tcp',
                                         '-auth', str(cookie), '-noreset']))
            await_value(lambda: Path('/tmp/.X11-unix/X87').is_socket(), 5)
            stage = 'bus'
            stack.enter_context(service(['/usr/bin/dbus-daemon', '--session', '--nofork', '--nopidfile',
                                         '--address=unix:path=' + str(address)]))
            await_value(address.is_socket, 5)
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi, Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync('org.a11y.Bus', '/org/a11y/bus', 'org.freedesktop.DBus.Properties', 'Set',
                GLib.Variant('(ssv)', ('org.a11y.Status', 'IsEnabled', GLib.Variant('b', True))),
                None, Gio.DBusCallFlags.NONE, 3000, None)
            Atspi.set_timeout(1000, 1500)
            Atspi.init()
            project_id = None
            for phase in ('first', 'second'):
                stage = phase + '_launch'
                with service(['/run/fixture/silex-desktop', '--stdio']) as app:
                    state['desktop_launches'] += 1
                    await_value(lambda: app.poll() is None and available())
                    if phase == 'first':
                        stage = 'seed_project'
                        created = remote('PUT', '/api/website?connectorId=fs-storage', {'name': NAME})
                        project_id = created['websiteId']
                        require(type(project_id) is str and UUID.fullmatch(project_id))
                        stage = 'refresh_dashboard'
                        desktop_action(Atspi, 'Refresh', app)
                    meta = remote('GET', '/api/website/meta?websiteId=' + project_id + '&connectorId=fs-storage')
                    require(meta['name'] == NAME)
                    stage = phase + '_open'
                    desktop_action(Atspi, 'Open project: ' + NAME, app)
                    stage = phase + '_editor'
                    window = await_value(lambda: visible_windows(NAME + ' — Silex'))
                    require(len(window) == 1 and await_value(webkit_process))
                    stage = phase + '_close'
                    request_close(window[0])
                    # waitid with WNOWAIT preserves ownership until the final drain.
                    def normal_exit():
                        observed = os.waitid(os.P_PID, app.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                        if observed:
                            require(observed.si_code == os.CLD_EXITED and observed.si_status == 0)
                        return observed
                    await_value(normal_exit, 9)
                    state['native_window_closes'] += 1
                await_value(lambda: not available(), 5)
            state['original_project_reopened'] = True
            state['project_id_sha256'] = hashlib.sha256(project_id.encode()).hexdigest()
            Atspi.exit()
        stage = 'cleanup'
        require(state['process_groups_started'] == state['process_groups_joined'] == 4)
        cookie.unlink()
        print(json.dumps(dict(status='passed', stage='complete', **state), sort_keys=True), flush=True)
    except BaseException:
        print(json.dumps(dict(status='failed', stage=stage, **state), sort_keys=True), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
