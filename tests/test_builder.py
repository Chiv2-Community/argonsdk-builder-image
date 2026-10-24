import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/builder.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = builder.lockfile(ROOT / 'build-lock.json')
        self.mod = {
            'name': 'ExampleMod',
            'repository': 'https://example.invalid/mod.git',
            'commit': 'a' * 40,
            'content_path': 'Content',
            'package_path': 'Mods/AgMods/ExampleMod',
        }

    def test_lock_uses_full_commits(self):
        for key in ('argon_sdk', 'engine_candidate'):
            self.assertRegex(self.lock[key]['commit'], '^[0-9a-f]{40}$')

    def test_rejects_moving_ref(self):
        self.lock['argon_sdk']['commit'] = 'main'
        path = self.root / 'lock.json'
        path.write_text(json.dumps(self.lock))
        with self.assertRaises(ValueError):
            builder.lockfile(path)

    def test_rejects_unsafe_mod_paths(self):
        path = self.root / 'mod.json'
        for value in ['../outside', '/Mods/Test', 'Mods/../Test', 'Mods//Test',
                      'Mods', 'C:\\Test', 'Mods/Test"', 'Mods/./Test']:
            with self.subTest(value=value):
                self.mod['package_path'] = value
                path.write_text(json.dumps(self.mod))
                with self.assertRaises(ValueError):
                    builder.mod_config(path)

    def test_accepts_flat_and_nested_mod_paths(self):
        path = self.root / 'mod.json'
        for value in ['Mods/ExampleMod', 'Mods/AgMods/ExampleMod']:
            self.mod['package_path'] = value
            path.write_text(json.dumps(self.mod))
            self.assertEqual(builder.mod_config(path)['package_path'], value)

    def test_rejects_unsafe_names_and_moving_mod_refs(self):
        path = self.root / 'mod.json'
        for key, value in [('name', '../escape'), ('commit', 'main'),
                           ('repository', 'file:///tmp/mod'), ('content_path', '../Content')]:
            with self.subTest(key=key):
                data = dict(self.mod, **{key: value})
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    builder.mod_config(path)

    def test_checkout_refuses_existing_directory(self):
        with patch.object(builder, 'run') as run:
            with self.assertRaises(ValueError):
                builder.checkout('unused', 'a' * 40, self.root)
            run.assert_not_called()

    def test_checkout_uses_recorded_gitlinks(self):
        with patch.object(builder, 'run') as run:
            builder.checkout('https://example.invalid/sdk.git', 'a' * 40, self.root / 'sdk')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[-1][-4:], ['submodule', 'update', '--init', '--recursive'])
        self.assertFalse(any('--remote' in command for command in commands))
        self.assertIn('a' * 40, commands[2])

    def test_prepare_copies_configured_content(self):
        def checkout(repo, commit, dest):
            (dest / 'Content').mkdir(parents=True)
            if dest.name == 'mod-source':
                (dest / 'Content/Test.uasset').write_bytes(b'asset')
        with patch.object(builder, 'checkout', side_effect=checkout):
            builder.prepare(self.lock, self.root, self.mod)
        self.assertTrue((self.root / 'ArgonSDK/Content/Mods/AgMods/ExampleMod/Test.uasset').exists())

    def test_prepare_without_mod_only_checks_out_sdk(self):
        with patch.object(builder, 'checkout') as checkout:
            builder.prepare(self.lock, self.root)
        self.assertEqual(checkout.call_count, 1)
        self.assertEqual(checkout.call_args.args[0], self.lock['argon_sdk']['repository'])

    def test_prepare_does_not_touch_existing_checkout(self):
        (self.root / 'ArgonSDK').mkdir()
        with patch.object(builder, 'checkout') as checkout:
            with self.assertRaises(ValueError):
                builder.prepare(self.lock, self.root)
            checkout.assert_not_called()

    def test_inventory_is_sorted_and_relative(self):
        (self.root / 'B.uexp').write_bytes(b'b')
        (self.root / 'A.uasset').write_bytes(b'a')
        entries = builder.inventory(self.root)
        self.assertEqual([rel for _, rel in entries], ['A.uasset', 'B.uexp'])

    def test_inventory_rejects_empty(self):
        with self.assertRaises(ValueError):
            builder.inventory(self.root)

    def test_inventory_rejects_unexpected_payload(self):
        (self.root / 'injected.dll').write_bytes(b'no')
        with self.assertRaises(ValueError):
            builder.inventory(self.root)

    @unittest.skipIf(builder.os.name == 'nt', 'Symlink permissions differ on Windows')
    def test_inventory_rejects_symlinks(self):
        (self.root / 'asset.uasset').write_bytes(b'asset')
        (self.root / 'link.uasset').symlink_to(self.root / 'asset.uasset')
        with self.assertRaises(ValueError):
            builder.inventory(self.root)

    def test_native_linux_rejects_windows_commands(self):
        with patch.object(builder, 'os', SimpleNamespace(name='posix')):
            for function, args in [
                (builder.cook, [self.root, self.root, self.mod]),
                (builder.build_editor, [self.root, self.root]),
                (builder.package, [self.root, self.root, self.root, self.lock, self.mod]),
            ]:
                with self.assertRaises(ValueError):
                    function(*args)

    def test_cook_disables_nativization_and_is_not_iterative(self):
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run') as run:
                builder.cook(self.root, self.root, self.mod)
        args = [str(arg) for arg in run.call_args.args[0]]
        self.assertIn('-TargetPlatform=WindowsNoEditor', args)
        self.assertTrue(any('BlueprintNativizationMethod=Disabled' in arg for arg in args))
        self.assertTrue(any(arg.startswith('-CookDir=') for arg in args))
        self.assertIn(f'-CookDir={self.root / "Content" / self.mod["package_path"]}', args)
        self.assertNotIn('-iterate', args)

    def test_cook_refuses_previous_output(self):
        (self.root / 'Saved/Cooked/WindowsNoEditor').mkdir(parents=True)
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run') as run:
                with self.assertRaises(ValueError):
                    builder.cook(self.root, self.root, self.mod)
                run.assert_not_called()

    def package_fixture(self):
        sdk = self.root / 'sdk'
        source = sdk / 'Content' / self.mod['package_path']
        cooked = sdk / 'Saved/Cooked/WindowsNoEditor/TBL/Content' / self.mod['package_path']
        source.mkdir(parents=True)
        cooked.mkdir(parents=True)
        (source / 'Test.uasset').write_bytes(b'source')
        (cooked / 'Test.uasset').write_bytes(b'cooked')
        (cooked / 'Test.uexp').write_bytes(b'bytecode')
        engine = self.root / 'engine'
        (engine / 'Engine/Build').mkdir(parents=True)
        (engine / 'Engine/Build/Build.version').write_text('{"MajorVersion":4,"MinorVersion":25}')
        return engine, sdk, self.root / 'dist'

    def test_package_manifest_and_mount(self):
        engine, sdk, output = self.package_fixture()

        def fake_run(args, log):
            Path(log).write_text('fake tool output')
            if any(str(arg).startswith('-Create=') for arg in args):
                Path(args[1]).write_bytes(b'fake pak')

        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run', side_effect=fake_run) as run:
                builder.package(engine, sdk, output, self.lock, self.mod)
        self.assertEqual(run.call_count, 3)
        response = (output / 'pak-inputs.txt').read_text()
        self.assertIn('"../../../TBL/Content/Mods/AgMods/ExampleMod/Test.uasset"', response)
        self.assertTrue((output / 'ExampleMod.pak').exists())
        self.assertTrue((output / 'ExampleMod.pak.sha256').exists())
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['mod'], self.mod)
        self.assertEqual(len(manifest['files']), 2)

    def test_package_rejects_missing_asset(self):
        engine, sdk, output = self.package_fixture()
        (sdk / 'Content' / self.mod['package_path'] / 'Missing.uasset').write_bytes(b'missing')
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with self.assertRaises(ValueError):
                builder.package(engine, sdk, output, self.lock, self.mod)
        self.assertFalse(output.exists())

    def test_package_never_replaces_output(self):
        engine, sdk, output = self.package_fixture()
        output.mkdir()
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with self.assertRaises(ValueError):
                builder.package(engine, sdk, output, self.lock, self.mod)


if __name__ == '__main__':
    unittest.main()
