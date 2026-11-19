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


def canvas_colors(project_id):
    digest = hashlib.sha256(project_id.encode('ascii')).digest()
    return bytes((208, digest[0], digest[1])), bytes((32, digest[2], digest[3]))


def saved_page(project_id):
    border, fill = canvas_colors(project_id)
    return {'id': 'native-home', 'name': 'Home', 'frames': [{'component': {
        'type': 'wrapper', 'components': [{'type': 'text', 'tagName': 'h1',
            'style': {'display': 'block', 'width': '230px', 'padding-bottom': '16px',
                      'border-left': '16px solid #' + border.hex(), 'background-color': '#' + fill.hex()},
            'components': [{'type': 'textnode', 'content': 'Restored canvas ' + project_id}]}]}}]}


def visible_titles(pid):
    # Search by the GTK client's PID. getwindowname reads the EWMH UTF-8 title
    # first; xdotool's regex name search reads the legacy WM_NAME instead.
    result = subprocess.run(['/usr/bin/xdotool', 'search', '--onlyvisible', '--pid', str(pid)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=False)
    if result.returncode == 1 and not result.stdout:
        return {}
    ids = result.stdout.splitlines()
    require(result.returncode == 0 and len(ids) <= 16 and all(row.isdigit() for row in ids))
    titles = {}
    for window in ids:
        item = subprocess.run(['/usr/bin/xdotool', 'getwindowname', window], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=2, check=False)
        if item.returncode == 0:  # A transient splash window can disappear.
            require(len(item.stdout) <= 512)
            titles[int(window)] = item.stdout.rstrip(b'\n').decode('utf-8', 'replace')
    return titles


def editor_window(pid):
    matches = [window for window, title in visible_titles(pid).items() if title == NAME + ' — Silex']
    require(len(matches) <= 1)
    return matches[0] if matches else None


def find_accessible(atspi, match):
    queue = [atspi.get_desktop(0)]
    for _ in range(2500):
        if not queue:
            return None
        node = queue.pop()
        if node is None:
            continue
        try:
            if result := match(node):
                return result
            count = node.get_child_count()
            require(0 <= count <= 1024)
            queue.extend(node.get_child_at_index(i) for i in range(count))
        except Exception as error:
            # WebKit replaces accessible objects while a new document is loading.
            if type(error).__module__.startswith('gi.repository'):
                continue
            raise
    raise RuntimeError('accessibility_tree_bound')


def editor_observation(atspi, pid, project_id):
    titles = set(visible_titles(pid).values())
    if '• ' + NAME + ' — Silex' in titles:
        return 'dirty_title'
    if project_id + ' — Silex' in titles:
        return 'id_title'
    page = 'unknown_page'

    def observe(node):
        nonlocal page
        if node.get_name() == 'Open project: ' + NAME:
            return 'dashboard'
        if node.get_name() == 'Loading':
            page = 'loading'
        document = node.get_document_iface()
        if document and page != 'loading':
            url = document.get_document_attribute_value('DocURL')
            if url in (f'http://localhost:{PORT}/?id={project_id}&connectorId=fs-storage',
                       f'http://127.0.0.1:{PORT}/?id={project_id}&connectorId=fs-storage'):
                page = 'editor_url'
        return None

    return find_accessible(atspi, observe) or page


def desktop_action(atspi, label, app_process):
    def match(node):
        if node.get_name() == label:
            action = node.get_action_iface()
            if action and action.get_n_actions():
                return action
        return None

    def locate():
        require(app_process.poll() is None)
        return find_accessible(atspi, match)

    require(await_value(locate).do_action(0))


def visible_canvas_heading(atspi, project_id):
    heading = 'Restored canvas ' + project_id

    def match(node):
        if node.get_name() != heading:
            text = node.get_text_iface()
            if not text or text.get_character_count() != len(heading) or text.get_text(0, len(heading)) != heading:
                return False
        states = node.get_state_set()
        return states.contains(atspi.StateType.VISIBLE) and states.contains(atspi.StateType.SHOWING)

    return find_accessible(atspi, match)


def contains_canvas_pixels(raw, width, height, stride, channels, colors):
    require(0 < width <= 1280 and 0 < height <= 800 and channels in (3, 4)
            and width * channels <= stride and len(raw) >= stride * (height - 1) + width * channels)
    border, fill = colors
    if channels == 4:
        border += b'\xff'
        fill += b'\xff'
    pattern = border * 8 + fill * 24
    last = -1
    run = 0
    for y in range(height):
        row = raw[y * stride:y * stride + width * channels]
        x = row.find(pattern)
        if x < 0 or x % channels:
            last, run = -1, 0
            continue
        run = run + 1 if x == last else 1
        if run == 6:
            return True
        last = x
    return False


def visual_canvas(gdk, gdkx, display, xid, project_id):
    window = gdkx.X11Window.foreign_new_for_display(display, xid)
    require(window is not None)
    width, height = window.get_width(), window.get_height()
    require(0 < width <= 1280 and 0 < height <= 800)
    pixbuf = gdk.pixbuf_get_from_window(window, 0, 0, width, height)
    return pixbuf is not None and contains_canvas_pixels(pixbuf.get_pixels(), width, height,
        pixbuf.get_rowstride(), pixbuf.get_n_channels(), canvas_colors(project_id))


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


def quit_dialog_action(node, pid):
    if node.get_name() != 'Quit' or node.get_process_id() != pid:
        return None
    buttons = node.get_parent()
    if buttons is None:
        return None
    count = buttons.get_child_count()
    if not 2 <= count <= 8:
        return None
    siblings = [buttons.get_child_at_index(index) for index in range(count)]
    if not any(sibling and sibling.get_name() == 'Save & Quit' for sibling in siblings):
        return None
    action = node.get_action_iface()
    return action if action and action.get_n_actions() else None


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
        native_window_closes=0, canvas_readbacks=[], close_actions=[], original_project_reopened=False)
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
        GDK_BACKEND='x11', GTK_A11Y='atspi', NO_AT_BRIDGE='0', LIBGL_ALWAYS_SOFTWARE='1', LC_ALL='C.UTF-8', LANG='C.UTF-8')
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
            gi.require_version('Gdk', '3.0')
            gi.require_version('GdkX11', '3.0')
            from gi.repository import Atspi, Gdk, GdkX11, Gio, GLib
            screen = Gdk.Display.open(os.environ['DISPLAY'])
            require(screen is not None)
            stack.callback(screen.close)
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
                        require(remote('GET', '/api/website?connectorId=fs-storage') == [])
                        created = remote('PUT', '/api/website?connectorId=fs-storage', {'name': NAME})
                        project_id = created['websiteId']
                        require(type(project_id) is str and UUID.fullmatch(project_id))
                        uri = '/api/website?websiteId=' + project_id + '&connectorId=fs-storage'
                        project = remote('GET', uri)
                        require(project['pages'] == [{}])
                        project['pages'] = [saved_page(project_id)]
                        remote('POST', uri, project)
                        stage = 'refresh_dashboard'
                        desktop_action(Atspi, 'Refresh', app)
                    stage = phase + '_list'
                    projects = remote('GET', '/api/website?connectorId=fs-storage')
                    require(type(projects) is list and len(projects) == 1 and projects[0]['websiteId'] == project_id
                            and projects[0]['name'] == NAME)
                    stage = phase + '_metadata'
                    meta = remote('GET', '/api/website/meta?websiteId=' + project_id + '&connectorId=fs-storage')
                    require(meta['name'] == NAME)
                    stage = phase + '_saved_page'
                    require(remote('GET', uri)['pages'] == [saved_page(project_id)])
                    stage = phase + '_open'
                    desktop_action(Atspi, 'Open project: ' + NAME, app)
                    stage = phase + '_editor'
                    try:
                        window = await_value(lambda: editor_window(app.pid))
                    except TimeoutError:
                        stage = phase + '_' + editor_observation(Atspi, app.pid, project_id)
                        raise
                    stage = phase + '_webkit_process'
                    require(await_value(webkit_process))
                    # Xvfb has no window manager to honor Tauri's maximize request.
                    # Size the confirmed project window to the full private display.
                    stage = phase + '_window_size'
                    subprocess.run(['/usr/bin/xdotool', 'windowsize', '--sync', str(window), '1280', '800'],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=True)
                    def read_canvas():
                        nonlocal stage
                        stage = phase + '_canvas_pixels'
                        if visual_canvas(Gdk, GdkX11, screen, window, project_id):
                            return 'visible_pixels'
                        stage = phase + '_canvas_accessibility'
                        if visible_canvas_heading(Atspi, project_id):
                            return 'accessible_text'
                        return None
                    try:
                        state['canvas_readbacks'].append(await_value(read_canvas))
                    except TimeoutError:
                        stage = phase + '_canvas_' + editor_observation(Atspi, app.pid, project_id)
                        raise
                    stage = phase + '_close_request'
                    request_close(window)
                    choice = 'window_close'
                    # Silex may mark the restored project changed while mounting the canvas.
                    # The saved fixture is already verified. Use the app's own Quit choice.
                    def normal_exit():
                        nonlocal choice, stage
                        observed = os.waitid(os.P_PID, app.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                        if observed:
                            stage = phase + '_exit_status'
                            require(observed.si_code == os.CLD_EXITED and observed.si_status == 0)
                            return True
                        if choice == 'window_close':
                            stage = phase + '_quit_dialog'
                            action = find_accessible(Atspi, lambda node: quit_dialog_action(node, app.pid))
                            if action:
                                stage = phase + '_quit_action'
                                require(action.do_action(0))
                                choice = 'quit_dialog'
                        else:
                            stage = phase + '_exit'
                        return False
                    await_value(normal_exit, 12)
                    state['native_window_closes'] += 1
                    state['close_actions'].append(choice)
                stage = phase + '_server_stop'
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
