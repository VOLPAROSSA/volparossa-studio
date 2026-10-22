# SPDX-License-Identifier: GPL-3.0-only
"""Inert reset-environment handoff checks, not sudo/privilege-drop acceptance."""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest

from runtime_context import CONTEXT_KEYS, read_context, write_context

ROOT = Path(__file__).resolve().parent


class ContextTests(unittest.TestCase):
    def values(self, temporary):
        return {'STUDIO_NODE': str(temporary / 'node/node'),
            'STUDIO_CHROME': '/usr/bin/google-chrome',
            'STUDIO_SILEX_SOURCE': str(temporary / 'silex'),
            'STUDIO_FIXTURE_TEMP': str(temporary),
            'STUDIO_ZIP_OUTPUT': str(temporary / 'actual-export.zip'),
            'STUDIO_BROWSER_RECEIPT': str(temporary / 'browser.json'),
            'RUNNER_TEMP': str(temporary.parent), 'HOME': pwd.getpwuid(os.getuid()).pw_dir}

    def test_reset_environment_recovers_exact_closed_context(self):
        with tempfile.TemporaryDirectory(prefix='studio-export-') as directory:
            temporary = Path(directory)
            path = temporary / 'runtime-context.json'
            expected = self.values(temporary)
            write_context(path, dict(expected, ACTIONS_RUNTIME_TOKEN='synthetic-never-carried'))
            # Emulate sudo env_reset: no STUDIO_*, RUNNER_TEMP or caller PATH.
            # The child executes only this standard-library handoff verifier.
            code = '''
import json,os,pathlib,sys
assert not any(k.startswith('STUDIO_') for k in os.environ)
assert 'RUNNER_TEMP' not in os.environ
sys.path.insert(0,sys.argv[1])
from runtime_context import read_context,restored_environment
values=read_context(pathlib.Path(sys.argv[2]))
env=restored_environment(values)
assert 'ACTIONS_RUNTIME_TOKEN' not in env
assert env['PATH']=='/usr/bin:/bin'
assert env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD']=='1'
print(json.dumps(values,sort_keys=True))
'''
            result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT), str(path)],
                                    env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True,
                                    timeout=3, check=True)
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual(set(json.loads(path.read_text())), CONTEXT_KEYS)

    def test_reject_broad_context_and_changed_paths(self):
        with tempfile.TemporaryDirectory(prefix='studio-export-') as directory:
            temporary = Path(directory)
            path = temporary / 'runtime-context.json'
            values = self.values(temporary)
            values['STUDIO_NODE'] = '/tmp/unassigned/node'
            with self.assertRaises(ValueError):
                write_context(path, values)
            values = self.values(temporary)
            write_context(path, values)
            values['PATH'] = '/tmp/unassigned/bin'
            path.write_text(json.dumps(values))
            with self.assertRaises(ValueError):
                read_context(path)

    def test_reject_symlink_and_nonprivate_context(self):
        with tempfile.TemporaryDirectory(prefix='studio-export-') as directory:
            temporary = Path(directory)
            path = temporary / 'runtime-context.json'
            write_context(path, self.values(temporary))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                read_context(path)
            path.chmod(0o600)
            alias = temporary / 'alias.json'
            alias.symlink_to(path)
            with self.assertRaises(OSError):
                read_context(alias)


if __name__ == '__main__':
    unittest.main()
