"""Encrypted transfer mechanics; not proof of cooker support under Wine."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bundle_windows_cooker as transfer


class WindowsTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, data=b'fixture'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_selection_keeps_runtime_and_shader_inputs_not_git_or_job_state(self):
        included = ['Engine/Binaries/Win64/Editor.dll', 'Engine/Shaders/Private/Test.usf',
                    'Engine/Plugins/Test/Test.uplugin', 'Engine/Plugins/Test/Binaries/Win64/Test.dll']
        excluded = ['.git/config', 'Engine/Intermediate/test.obj', 'Engine/DerivedDataCache/Boot.ddc',
                    'Engine/Programs/UnrealPak/Saved/log.txt', 'Engine/Plugins/Test/Saved/log.txt']
        for path in included + excluded:
            self.write('engine/' + path)
        files = transfer.selected_files(self.root / 'engine')
        self.assertEqual({p.relative_to(self.root / 'engine').as_posix() for p in files}, set(included))

    def test_archive_records_file_hashes_and_separate_roots(self):
        self.write('engine/Engine/Binaries/Win64/Editor.dll')
        self.write('sdk/Binaries/Win64/UE4Editor-TBL.dll')
        with patch.object(transfer.workspace, 'engine_identity', return_value={'pin': 'engine'}), \
             patch.object(transfer.workspace, 'verified_sdk', return_value={'pin': 'sdk'}), \
             patch.object(transfer.workspace, 'verify_inputs', return_value={'inputs': []}):
            archive = self.root / 'private/cooker.zip'
            manifest = transfer.bundle(self.root / 'engine', self.root / 'sdk', archive,
                                       {'engine': {}, 'argon_sdk': {'commit': 'test'}})
        with zipfile.ZipFile(archive) as stream:
            self.assertEqual(json.loads(stream.read('manifest.json')), manifest)
            for row in manifest['files']:
                self.assertEqual(len(stream.read(row['path'])), row['size'])
        self.assertEqual({row['path'].split('/')[0] for row in manifest['files']}, {'engine', 'sdk'})

    def test_workload_inputs_cannot_enter_reusable_bundle(self):
        with patch.object(transfer.workspace, 'engine_identity', return_value={}), \
             patch.object(transfer.workspace, 'verified_sdk', return_value={}), \
             patch.object(transfer.workspace, 'verify_inputs', return_value={'inputs': ['mod']}):
            with self.assertRaisesRegex(ValueError, 'workload-free'):
                transfer.bundle(self.root / 'engine', self.root / 'sdk', self.root / 'cooker.zip',
                                {'engine': {}, 'argon_sdk': {'commit': 'test'}})

    def test_rejects_bad_recipient_before_invoking_tool(self):
        for recipient in ['', '-password', 'age1short', 'age1' + 'Q' * 58]:
            with self.subTest(recipient=recipient), patch.object(transfer.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'recipient'):
                    transfer.seal(self.root / 'cooker.zip', self.root / 'out', 'age', recipient)
                run.assert_not_called()

    def test_plaintext_must_stay_outside_upload_directory(self):
        with self.assertRaisesRegex(ValueError, 'Plaintext'):
            transfer.seal(self.root / 'upload/cooker.zip', self.root / 'upload',
                          'age', 'age1' + 'q' * 58)

    def test_existing_upload_directory_is_not_reused(self):
        (self.root / 'upload').mkdir()
        with self.assertRaises(FileExistsError):
            transfer.seal(self.root / 'cooker.zip', self.root / 'upload',
                          'age', 'age1' + 'q' * 58)

    @unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'), 'age tools required')
    def test_real_age_roundtrip_and_ciphertext_only_upload_directory(self):
        key = self.root / 'identity'
        subprocess.run(['age-keygen', '-o', str(key)], check=True, capture_output=True)
        recipient = subprocess.check_output(['age-keygen', '-y', str(key)], text=True).strip()
        archive = self.write('private/cooker.zip', b'licensed-fixture-bytes')
        output = self.root / 'upload'
        report = transfer.seal(archive, output, shutil.which('age'), recipient)
        self.assertEqual({p.name for p in output.iterdir()}, {'windows-cooker.zip.age', 'transfer.json'})
        plain = subprocess.check_output(['age', '--decrypt', '-i', str(key),
                                         str(output / 'windows-cooker.zip.age')])
        self.assertEqual(plain, archive.read_bytes())
        self.assertNotIn(archive.read_bytes(), (output / 'windows-cooker.zip.age').read_bytes())
        self.assertEqual(report['ciphertext_sha256'], transfer.workspace.file_hash(output / 'windows-cooker.zip.age'))

    def test_workflow_uploads_only_explicit_ciphertext_and_transfer_metadata(self):
        workflow = (ROOT / '.github/workflows/windows-wine-probe.yml').read_text()
        upload = workflow.split('- uses: actions/upload-artifact@', 1)[1]
        self.assertIn('/cooker-encrypted/windows-cooker.zip.age', upload)
        self.assertIn('/cooker-encrypted/transfer.json', upload)
        self.assertNotIn('cooker-private', upload)
        self.assertNotIn('*', upload)
        self.assertIn('retention-days: 1', upload)


if __name__ == '__main__':
    unittest.main()
