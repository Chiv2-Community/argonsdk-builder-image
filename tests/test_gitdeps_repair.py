import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import engine_tools


class GitdepsRepairTests(unittest.TestCase):
    def setUp(self):
        self.before = (b'<Manifest>\n'
                       b'<File Name="keep" Hash="retained" />\n'
                       b'<File Hash="6071ee317be416093d0f44670e1609a7f66a8063" />\n'
                       b'<Blob Hash="6071ee317be416093d0f44670e1609a7f66a8063" />\n'
                       b'<Pack Hash="60079f44b8b7b6c3f432fb78bff5b16074a33000" />\n'
                       b'</Manifest>\n')
        self.after = b'<Manifest>\n<File Name="keep" Hash="retained" />\n</Manifest>\n'

    def test_exact_fix_preserves_line_endings(self):
        with patch.object(engine_tools, 'GITDEPS_BEFORE', hashlib.sha256(self.before).hexdigest()), \
             patch.object(engine_tools, 'GITDEPS_AFTER', hashlib.sha256(self.after).hexdigest()):
            self.assertEqual(engine_tools.repaired_gitdeps(self.before), self.after)
            self.assertEqual(engine_tools.repaired_gitdeps(self.before.replace(b'\n', b'\r\n')),
                             self.after.replace(b'\n', b'\r\n'))

    def test_unknown_manifest_is_not_rewritten(self):
        self.assertEqual(engine_tools.repaired_gitdeps(self.before), self.before)

    def test_unexpected_repair_output_is_rejected(self):
        with patch.object(engine_tools, 'GITDEPS_BEFORE', hashlib.sha256(self.before).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'exact upstream'):
                engine_tools.repaired_gitdeps(self.before)

    def test_transport_records_upstream_fix_in_provenance(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(engine_tools, 'GITDEPS_BEFORE', hashlib.sha256(self.before).hexdigest()), \
             patch.object(engine_tools, 'GITDEPS_AFTER', hashlib.sha256(self.after).hexdigest()):
            root = Path(directory)
            manifest = root / 'Engine/Build/Commit.gitdeps.xml'
            toolchain = root / 'Engine/Build/BatchFiles/Linux/SetupToolchain.sh'
            toolchain.parent.mkdir(parents=True)
            manifest.write_bytes(self.before)
            toolchain.write_bytes(b'http://cdn.unrealengine.com/fixture')
            engine_tools.https_transport(root)
            records = json.loads((root / '.builder-transport.json').read_text())
            self.assertEqual(manifest.read_bytes(), self.after)
            self.assertEqual(records[0]['upstream_dependency_fix']['commit'], engine_tools.GITDEPS_FIX)
            self.assertEqual(records[0]['before'], hashlib.sha256(self.before).hexdigest())
            self.assertEqual(records[0]['after'], hashlib.sha256(self.after).hexdigest())
