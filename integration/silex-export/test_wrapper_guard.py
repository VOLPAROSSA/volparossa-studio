# SPDX-License-Identifier: GPL-3.0-only
"""Execute only rejecting guards: never reach sudo, unshare or namespace creation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CORE = Path(sys.argv.pop(1)).resolve()
SCRIPT = CORE / 'scripts/run-isolated-test.sh'


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
            result = subprocess.run([str(SCRIPT), '--studio-nonroot-command', *arguments],
                                    env=env, text=True, capture_output=True, timeout=3)
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


if __name__ == '__main__':
    unittest.main()
