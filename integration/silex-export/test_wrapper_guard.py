# SPDX-License-Identifier: GPL-3.0-only
"""Validate only the shell prefix; never reach tools, sudo, probes or namespaces."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CORE = Path(sys.argv.pop(1)).resolve()
SCRIPT = CORE / 'scripts/run-isolated-test.sh'
# Exact prefix from the actual wrapper. Terminate before even executable tool
# checks: accepted controls can never reach sudo/unshare/probe on this host.
BOUNDARY = 'for test_tool in /usr/bin/unshare '
SOURCE = SCRIPT.read_text()
if SOURCE.count(BOUNDARY) != 1:
    raise ValueError('wrapper prefix boundary changed')
PREFIX = SOURCE.split(BOUNDARY, 1)[0] + "printf 'INERT_STUDIO_GUARD_ACCEPTED\\n'\nexit 0\n"


def validate_prefix(arguments, env):
    return subprocess.run(['/bin/sh', '-s', '--', '--studio-nonroot-command', *arguments],
                          input=PREFIX, env=env, text=True, capture_output=True, timeout=3)



class GuardTests(unittest.TestCase):
    def check_rejection(self, replacement, message, environment=None):
        with tempfile.TemporaryDirectory(prefix='studio-export-') as directory:
            root = Path(directory)
            runtime = root / 'studio-export-synthetic' / 'fixture' / 'runtime.py'
            runtime.parent.mkdir(parents=True)
            runtime.write_text('# inert guard fixture, never executed\n')
            arguments = ['/usr/bin/python3', 'studio_export',
                         'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', str(runtime)]
            for index, value in replacement.items():
                arguments[index] = value(root) if callable(value) else value
            env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                       RUNNER_TEMP=str(root), VOLPAROSSA_TEST_ALLOW_SUDO_NETNS='1')
            env.update(environment or {})
            result = validate_prefix(arguments, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertNotIn('isolated-test: explicit sudo fallback', result.stdout)
            self.assertNotIn('new disposable', result.stdout)

    def test_fixed_label_marker_loopback(self):
        for index, value in ((1, 'another_label'), (2, 'VOLPAROSSA_DNS_CACHE_PARENT_NETNS'), (3, 'none')):
            with self.subTest(index=index):
                self.check_rejection({index: value}, 'fixed command label, marker and loopback')

    def test_fixed_executable(self):
        self.check_rejection({0: '/bin/sh'}, 'requires system Python')

    def test_fixed_arguments(self):
        self.check_rejection({4: '-c'}, 'exact Python arguments')

    def test_script_path_boundary(self):
        self.check_rejection({5: '/tmp/unassigned/runtime.py'}, 'temporary runtime script')

    def test_script_path_cannot_escape_through_temporary_prefix(self):
        self.check_rejection({5: lambda root: str(root / 'studio-export-a/../other/fixture/runtime.py')},
                             'temporary directory is invalid')

    def test_hosted_execution_boundary(self):
        self.check_rejection({}, 'requires the disposable hosted runner', {'GITHUB_ACTIONS': 'false'})

    def test_explicit_existing_sudo_authorization(self):
        self.check_rejection({}, 'explicit sudo namespace authorization',
                             {'VOLPAROSSA_TEST_ALLOW_SUDO_NETNS': '0'})

    def test_both_fixed_entrypoints_and_reject_other_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'studio-export-synthetic' / 'fixture'
            fixture.mkdir(parents=True)
            for name in ('runtime.py', 'viewer_runtime.py', 'other_runtime.py'):
                (fixture / name).write_text('# inert source, never executed\n')
            env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                       RUNNER_TEMP=str(root), VOLPAROSSA_TEST_ALLOW_SUDO_NETNS='1')
            arguments = ['/usr/bin/python3', 'studio_export',
                         'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B']
            for name in ('runtime.py', 'viewer_runtime.py'):
                with self.subTest(allowed=name):
                    result = validate_prefix([*arguments, str(fixture / name)], env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, 'INERT_STUDIO_GUARD_ACCEPTED\n')
            for name in ('other_runtime.py', 'viewer-runtime.py', 'runtime.py/../viewer_runtime.py'):
                with self.subTest(denied=name):
                    result = validate_prefix([*arguments, str(fixture / name)], env)
                    self.assertNotEqual(result.returncode, 0)
            # A direct symlink and symlinked fixture/temp parent must all fail.
            for name in ('runtime.py', 'viewer_runtime.py'):
                path = fixture / name
                path.unlink()
                path.symlink_to('/usr/bin/python3')
                result = validate_prefix([*arguments, str(path)], env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('regular file', result.stderr)
                path.unlink()
                path.write_text('# inert source\n')
            target = root / 'real-fixture'
            fixture.rename(target)
            fixture.symlink_to(target, target_is_directory=True)
            result = validate_prefix([*arguments, str(fixture / 'viewer_runtime.py')], env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('real directories', result.stderr)
            fixture.unlink()
            target.rename(fixture)
            parent = fixture.parent
            real_parent = root / 'real-parent'
            parent.rename(real_parent)
            parent.symlink_to(real_parent, target_is_directory=True)
            result = validate_prefix([*arguments, str(fixture / 'viewer_runtime.py')], env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('real directories', result.stderr)

    def test_argument_count_is_closed_for_both_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'studio-export-synthetic' / 'fixture'
            fixture.mkdir(parents=True)
            env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                       RUNNER_TEMP=str(root), VOLPAROSSA_TEST_ALLOW_SUDO_NETNS='1')
            arguments = ['/usr/bin/python3', 'studio_export',
                         'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B']
            for name in ('runtime.py', 'viewer_runtime.py'):
                path = fixture / name
                path.touch()
                for extra in ([], [str(path), 'unexpected']):
                    result = validate_prefix([*arguments, *extra], env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('exact Python arguments', result.stderr)


if __name__ == '__main__':
    unittest.main()
