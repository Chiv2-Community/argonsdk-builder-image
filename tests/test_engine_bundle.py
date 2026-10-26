"""Archive mechanics only; hosted cooking is the engine-reuse acceptance test."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_engine_reuse as reuse


class EngineReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = self.root / 'ue'
        self.engine.mkdir()
        (self.engine / '.builder-engine.json').write_text('{}')
        (self.engine / 'Engine/Binaries').mkdir(parents=True)
        (self.engine / 'Engine/Binaries/Editor.dll').write_bytes(b'compiled editor')
        (self.engine / 'Engine/Empty').mkdir()
        (self.engine / 'Engine/source.cpp').write_bytes(b'source')
        self.storage = self.root / 'bundle'

    def test_roundtrip_preserves_inventory_and_keeps_original(self):
        before = reuse.inventory(self.engine)
        report = reuse.roundtrip(self.engine, self.storage, reserve=0)
        self.assertEqual(reuse.inventory(self.engine), before)
        self.assertEqual(reuse.inventory(self.storage / 'original-engine'), before)
        self.assertTrue((self.engine / 'Engine/Empty').is_dir())
        self.assertEqual(report['verification'], 'engine_archive_roundtrip_passed')
        self.assertEqual(report['tree_bytes'], sum(row['size'] for row in before))
        self.assertGreater(report['archive_bytes'], 0)
        self.assertEqual(report['cross_runner_validation'], 'not_run')
        self.assertEqual(reuse.verify_products(self.engine, self.storage)['products'], 1)

    def test_detects_modified_missing_added_and_rebuilt_products(self):
        reuse.roundtrip(self.engine, self.storage, reserve=0)
        product = self.engine / 'Engine/Binaries/Editor.dll'
        original = product.read_bytes()
        timestamp = product.stat().st_mtime_ns
        product.write_bytes(b'changed editor')
        with self.assertRaisesRegex(ValueError, 'build products changed'):
            reuse.verify_products(self.engine, self.storage)
        product.write_bytes(original)
        os.utime(product, ns=(timestamp, timestamp + 2000000000))
        with self.assertRaisesRegex(ValueError, 'build products changed'):
            reuse.verify_products(self.engine, self.storage)
        product.unlink()
        with self.assertRaisesRegex(ValueError, 'build products changed'):
            reuse.verify_products(self.engine, self.storage)
        product.write_bytes(original)
        os.utime(product, ns=(timestamp, timestamp))
        (product.parent / 'New.obj').write_bytes(b'new object')
        with self.assertRaisesRegex(ValueError, 'build products changed'):
            reuse.verify_products(self.engine, self.storage)

    def test_generated_logs_are_not_engine_recompilation(self):
        reuse.roundtrip(self.engine, self.storage, reserve=0)
        (self.engine / 'Engine/Log.txt').write_text('consumer log')
        self.assertEqual(reuse.verify_products(self.engine, self.storage)['products'], 1)

    def test_refuses_git_metadata_and_missing_receipt(self):
        (self.engine / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'Git metadata'):
            reuse.roundtrip(self.engine, self.storage, reserve=0)
        (self.engine / '.git').rmdir()
        (self.engine / '.builder-engine.json').unlink()
        with self.assertRaisesRegex(ValueError, 'receipt'):
            reuse.roundtrip(self.engine, self.storage, reserve=0)

    def test_refuses_overlapping_or_existing_storage(self):
        with self.assertRaisesRegex(ValueError, 'separate trees'):
            reuse.roundtrip(self.engine, self.engine / 'bundle', reserve=0)
        self.storage.mkdir()
        with self.assertRaises(FileExistsError):
            reuse.roundtrip(self.engine, self.storage, reserve=0)

    def test_insufficient_space_leaves_original_untouched(self):
        before = reuse.inventory(self.engine)
        with patch.object(reuse.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
            with self.assertRaisesRegex(ValueError, 'Insufficient space'):
                reuse.roundtrip(self.engine, self.storage, reserve=0)
        self.assertEqual(reuse.inventory(self.engine), before)


if __name__ == '__main__':
    unittest.main()
