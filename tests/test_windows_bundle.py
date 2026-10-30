import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import windows_bundle


class WindowsBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = {'engine': {'commit': 'e' * 40}, 'argon_sdk': {'commit': 'a' * 40}}

    def archive(self, name='engine/file.dll', data=b'fixture', expected=None, extra=False, dirty=False):
        manifest = {'schema_version': 1, 'engine': self.lock['engine'],
                    'sdk': {'commit': 'a' * 40, 'dirty': dirty},
                    'files': [{'path': name, 'size': len(data),
                               'sha256': hashlib.sha256(data if expected is None else expected).hexdigest()}]}
        archive = self.root / 'archive.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr(name, data)
            stream.writestr('manifest.json', json.dumps(manifest))
            if extra:
                stream.writestr('engine/extra.dll', b'extra')
        return archive

    def test_extract_verifies_contents_and_preserves_manifest(self):
        archive = self.archive()
        target = self.root / 'out'
        result = windows_bundle.extract(archive, target, self.lock)
        self.assertEqual((target / 'engine/file.dll').read_bytes(), b'fixture')
        self.assertEqual(json.loads((target / 'manifest.json').read_text()), result)

    def test_rejects_traversal_absolute_and_foreign_roots_before_creating_output(self):
        for name in ['../escape', '/engine/file', 'engine/../../escape', 'engine\\file',
                     'C:/file', 'other/file', 'engine/./file', 'engine//file']:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    windows_bundle.extract(self.archive(name), self.root / 'out', self.lock)
                self.assertFalse((self.root / 'out').exists())

    def test_rejects_unlisted_members_and_dirty_sdk(self):
        with self.assertRaisesRegex(ValueError, 'members'):
            windows_bundle.extract(self.archive(extra=True), self.root / 'out', self.lock)
        with self.assertRaisesRegex(ValueError, 'source pins'):
            windows_bundle.extract(self.archive(dirty=True), self.root / 'out', self.lock)

    def test_rejects_changed_payload_and_existing_destination(self):
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            windows_bundle.extract(self.archive(expected=b'other'), self.root / 'out', self.lock)
        with self.assertRaisesRegex(ValueError, 'must be new'):
            windows_bundle.extract(self.root / 'archive.zip', self.root / 'out', self.lock)


if __name__ == '__main__':
    unittest.main()
