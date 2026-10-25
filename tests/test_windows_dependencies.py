"""Run the production completion guard, including hidden Windows manifests."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required')
class WindowsDependenciesTests(unittest.TestCase):
    def guard(self, root):
        return subprocess.run(['pwsh', '-NoProfile', '-File',
                               str(ROOT / 'scripts/check-windows-dependencies.ps1'),
                               '-Engine', str(root)], capture_output=True, text=True)

    def test_hidden_nonempty_manifest_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / '.ue4dependencies'
            manifest.write_bytes(b'completed dependencies')
            if sys.platform == 'win32':
                if not ctypes.windll.kernel32.SetFileAttributesW(str(manifest), 2):
                    raise ctypes.WinError()
            result = self.guard(temp)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_and_empty_manifests_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertNotEqual(self.guard(temp).returncode, 0)
            manifest = Path(temp) / '.ue4dependencies'
            manifest.touch()
            self.assertNotEqual(self.guard(temp).returncode, 0)

    def test_directory_is_not_a_completion_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / '.ue4dependencies').mkdir()
            self.assertNotEqual(self.guard(temp).returncode, 0)
