"""Synthetic engine identity tests; no real toolchain is executed."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import engine_tools
from fixtures import engine_fixture


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pin = json.loads((ROOT / 'build-lock.json').read_text())['engine']

    def test_correct_linux_engine_receipt(self):
        engine_fixture(self.root, self.pin, 'Linux')
        result = engine_tools.identity(self.root, self.pin, 'Linux')
        self.assertEqual(result['verification'], 'build_receipt_hashes')
        self.assertEqual(result['branch'], '4.25-plus')
        self.assertEqual(result['commit'], self.pin['commit'])

    def test_archive_toolchain_cache_is_not_mistaken_for_git_metadata(self):
        engine_fixture(self.root, self.pin, 'Linux')
        (self.root / '.git/ue4-sdks').mkdir(parents=True)
        result = engine_tools.identity(self.root, self.pin, 'Linux')
        self.assertEqual(result['verification'], 'build_receipt_hashes')

    def test_stock_425_is_rejected_even_with_matching_receipt(self):
        engine_fixture(self.root, self.pin)
        version_file = self.root / 'Engine/Build/Build.version'
        version = json.loads(version_file.read_text())
        version['BranchName'] = '++UE4+Release-4.25'
        version_file.write_text(json.dumps(version))
        with self.assertRaisesRegex(ValueError, 'not stock UE 4.25'):
            engine_tools.identity(self.root, self.pin)

    def test_unpinned_or_other_branch_is_rejected(self):
        for changes in [{'branch': '4.25'}, {'branch': '4.26'}, {'commit': 'main'}]:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    engine_tools.validate_pin(dict(self.pin, **changes))

    def test_modified_tool_is_rejected(self):
        engine_fixture(self.root, self.pin)
        (self.root / 'Engine/Binaries/Win64/UnrealPak.exe').write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'file mismatch'):
            engine_tools.identity(self.root, self.pin)

    def test_receipt_revision_mismatch_is_rejected(self):
        engine_fixture(self.root, self.pin)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            engine_tools.identity(self.root, dict(self.pin, commit='0' * 40))

    def test_receipt_requires_all_tools_and_correct_platform(self):
        engine_fixture(self.root, self.pin)
        with self.assertRaisesRegex(ValueError, 'platform'):
            engine_tools.identity(self.root, self.pin, 'Linux')
        path = self.root / engine_tools.RECEIPT
        receipt = json.loads(path.read_text())
        del receipt['files']['Engine/Binaries/Win64/UnrealPak.exe']
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'missing required'):
            engine_tools.identity(self.root, self.pin)

    def test_https_transport_records_only_the_isolated_copy(self):
        paths = ['Engine/Build/Commit.gitdeps.xml', 'Engine/Build/BatchFiles/Linux/SetupToolchain.sh']
        for rel in paths:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('url=http://cdn.unrealengine.com/fixture')
        engine_tools.https_transport(self.root)
        for rel in paths:
            self.assertIn('https://cdn.unrealengine.com/', (self.root / rel).read_text())
        changes = json.loads((self.root / '.builder-transport.json').read_text())
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(entry['before'] != entry['after'] for entry in changes))

    @unittest.skipIf(sys.platform == 'win32', 'Tests the Linux setup shell wrapper')
    def test_dependency_setup_does_not_combine_prompt_and_force(self):
        batch = self.root / 'Engine/Build/BatchFiles/Linux'
        batch.mkdir(parents=True)
        dependency_script = batch / 'GitDependencies.sh'
        dependency_script.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > dependency-args\necho complete > .ue4dependencies\n')
        dependency_script.chmod(0o755)
        (batch / 'Setup.sh').write_text('exit 0\n')
        subprocess.run(['bash', str(ROOT / 'scripts/build-engine.sh'), 'setup'], cwd=self.root, check=True)
        args = (self.root / 'dependency-args').read_text().splitlines()
        self.assertIn('--force', args)
        self.assertNotIn('--prompt', args)

    @unittest.skipIf(sys.platform == 'win32', 'Tests the Linux setup shell wrapper')
    def test_successful_exit_without_dependency_manifest_is_rejected(self):
        batch = self.root / 'Engine/Build/BatchFiles/Linux'
        batch.mkdir(parents=True)
        dependency_script = batch / 'GitDependencies.sh'
        dependency_script.write_text('#!/bin/bash\nexit 0\n')
        dependency_script.chmod(0o755)
        (batch / 'Setup.sh').write_text('exit 0\n')
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run(['bash', str(ROOT / 'scripts/build-engine.sh'), 'setup'], cwd=self.root, check=True)


if __name__ == '__main__':
    unittest.main()
