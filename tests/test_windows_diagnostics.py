"""Collect diagnostics only, including hidden receipts and separate roots."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required')
class WindowsDiagnosticsTests(unittest.TestCase):
    def collect(self, root):
        return subprocess.run([
            'pwsh', '-NoProfile', '-File', str(ROOT / 'scripts/collect-windows-diagnostics.ps1'),
            '-Engine', str(root / 'engine'), '-Workspace', str(root / 'workspace'),
            '-Output', str(root / 'upload'), '-RuntimeTemp', str(root / 'temp'),
        ], capture_output=True, text=True)

    def test_whitelisted_files_share_a_single_upload_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {
                'engine/.builder-engine.json': 'receipt',
                'engine/.builder-transport.json': 'transport',
                'engine/Engine/Programs/UnrealBuildTool/Log.txt': 'ubt',
                'engine/Engine/Saved/UnrealBuildTool/BuildConfiguration.xml': 'configuration',
                'workspace/ArgonSDK/Saved/Logs/TBL.log': 'editor',
                'temp/windows-builder-validation.json': 'validation',
                'temp/windows-runtime-smoke.log': 'smoke',
                'temp/dd_setup_test_errors.log': 'installer',
                'engine/Engine/Binaries/Win64/UE4Editor-Cmd.exe': 'must not upload',
                'workspace/dist/test.pak': 'must not upload',
                'temp/mod-descriptor.json': 'must not upload',
            }
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            if sys.platform == 'win32':
                receipt = root / 'engine/.builder-engine.json'
                if not ctypes.windll.kernel32.SetFileAttributesW(str(receipt), 2):
                    raise ctypes.WinError()
            result = self.collect(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            contents = {p.relative_to(root / 'upload').as_posix(): p.read_text()
                        for p in (root / 'upload').rglob('*') if p.is_file()}
            self.assertEqual(contents, {
                'engine-receipt.json': 'receipt', 'engine-transport.json': 'transport',
                'BuildConfiguration.xml': 'configuration', 'ubt/Log.txt': 'ubt',
                'editor/TBL.log': 'editor', 'windows-builder-validation.json': 'validation',
                'windows-runtime-smoke.log': 'smoke', 'installer/dd_setup_test_errors.log': 'installer',
            })
            if sys.platform == 'win32':
                attributes = ctypes.windll.kernel32.GetFileAttributesW(str(root / 'upload/engine-receipt.json'))
                self.assertEqual(attributes & 2, 0, 'Hidden receipts must not be omitted by upload-artifact')
            self.assertNotEqual(self.collect(root).returncode, 0)

    def test_early_build_failure_with_no_logs_can_be_collected(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.collect(Path(temp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
