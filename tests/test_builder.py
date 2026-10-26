import importlib.util
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/builder.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
from fixtures import engine_fixture


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
        for key in ('argon_sdk', 'engine'):
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
            if dest.name == '0':
                (dest / 'Content/Test.uasset').write_bytes(b'asset')
        with patch.object(builder, 'checkout', side_effect=checkout):
            with patch.object(builder.workspace, 'verified_sdk', return_value={'commit': 'test'}):
                builder.prepare(self.lock, self.root, self.mod)
        self.assertTrue((self.root / 'ArgonSDK/Content/Mods/AgMods/ExampleMod/Test.uasset').exists())

    def test_prepare_without_mod_only_checks_out_sdk(self):
        with patch.object(builder, 'checkout') as checkout:
            def make_sdk(repo, commit, dest):
                dest.mkdir()
            checkout.side_effect = make_sdk
            with patch.object(builder.workspace, 'verified_sdk', return_value={'commit': 'test'}):
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
                (builder.build_editor, [self.root, self.root, self.lock]),
                (builder.package, [self.root, self.root, self.root, self.lock, self.mod]),
            ]:
                with self.assertRaises(ValueError):
                    function(*args)

    def test_cook_disables_nativization_and_is_not_iterative(self):
        engine, sdk, _ = self.package_fixture()
        cooked = sdk / 'Saved/Cooked/WindowsNoEditor'
        # Simulate a real cook creating output only after invocation.
        saved = sdk / 'Saved/fixture'
        cooked.rename(saved)
        def fake_cook(args):
            saved.rename(cooked)
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run', side_effect=fake_cook) as run:
                builder.cook(engine, sdk, self.mod)
        args = [str(arg) for arg in run.call_args.args[0]]
        self.assertIn('-TargetPlatform=WindowsNoEditor', args)
        self.assertTrue(any('BlueprintNativizationMethod=Disabled' in arg for arg in args))
        self.assertIn('-cooksinglepackage', args)
        self.assertIn('-skipeditorcontent', args)
        self.assertIn('-Map=/Game/Mods/AgMods/ExampleMod/Test', args)
        self.assertFalse(any(arg.startswith('-CookDir=') for arg in args))
        self.assertNotIn('-iterate', args)
        receipt = json.loads((sdk / builder.COOK_RECEIPT).read_text())
        self.assertEqual(receipt['verification'], 'cook_command_returned_zero')
        self.assertEqual(len(receipt['files']), 2)
        self.assertEqual(receipt['requested_packages'], ['/Game/Mods/AgMods/ExampleMod/Test'])
        self.assertEqual(receipt['commands'], [args])
        self.assertIn(f'-DefGameIni={sdk.resolve() / "Saved/BuilderCook/DefaultGame.ini"}', args)
        config = sdk / receipt['game_config_override']['path']
        self.assertEqual(builder.file_hash(config), receipt['game_config_override']['sha256'])

    def test_cook_uses_derived_config_without_modifying_sdk_defaults(self):
        source = self.root / 'Config/DefaultGame.ini'
        source.parent.mkdir()
        before = b'[/Script/UnrealEd.ProjectPackagingSettings]\r\n+DirectoriesToAlwaysCook=(Path="/Game/Mods")\r\n'
        source.write_bytes(before)
        receipt = builder.cook_game_config(self.root)
        derived = self.root / receipt['path']
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(derived.read_bytes().startswith(before))
        self.assertIn(b'!DirectoriesToAlwaysCook=ClearArray', derived.read_bytes())
        self.assertIn(b'!MapsToCook=ClearArray', derived.read_bytes())
        self.assertEqual(builder.file_hash(derived), receipt['sha256'])
        with self.assertRaises(FileExistsError):
            builder.cook_game_config(self.root)

    def test_cook_enumerates_only_mod_assets_and_maps(self):
        engine, sdk, _ = self.package_fixture()
        source = sdk / 'Content' / self.mod['package_path']
        (source / 'Sub').mkdir()
        (source / 'Sub/Level.umap').write_bytes(b'map')
        (source / 'Test.uexp').write_bytes(b'not a root package')
        (sdk / 'Content/Unrelated.uasset').write_bytes(b'not this mod')
        self.assertEqual(builder.cook_packages(sdk, self.mod), [
            '/Game/Mods/AgMods/ExampleMod/Sub/Level', '/Game/Mods/AgMods/ExampleMod/Test'])

    def test_cook_rejects_ambiguous_package_names(self):
        _, sdk, _ = self.package_fixture()
        for name in ['Bad+Name.uasset', 'Bad Name.uasset', 'Bad.Name.uasset', 'Test.umap']:
            path = sdk / 'Content' / self.mod['package_path'] / name
            path.write_bytes(b'bad')
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    builder.cook_packages(sdk, self.mod)
            path.unlink()

    def test_cook_batches_by_package_count_and_encoded_command_length(self):
        for packages in [
            [f'/Game/Mods/Example/Asset{i:04}' for i in range(501)],
            ['/Game/Mods/Example/' + 'x' * 200 + str(i) for i in range(250)],
            ['/Game/Mods/Example/' + '\U0001f600' * 150 + str(i) for i in range(150)],
        ]:
            commands = builder.cook_commands(self.root, self.root, packages)
            self.assertGreater(len(commands), 1)
            roots = []
            for index, command in enumerate(commands):
                text = builder.subprocess.list2cmdline([str(arg) for arg in command])
                self.assertLess(len(text.encode('utf-16-le')) // 2, builder.MAX_COOK_COMMAND_UNITS)
                batch = next(arg for arg in command if str(arg).startswith('-Map='))[5:].split('+')
                self.assertLessEqual(len(batch), builder.MAX_COOK_PACKAGES)
                self.assertEqual('-iterate' in command, index > 0)
                roots.extend(batch)
            self.assertEqual(roots, packages)

    def test_cook_refuses_single_package_exceeding_command_limit(self):
        with self.assertRaisesRegex(ValueError, 'command-line limit'):
            builder.cook_commands(self.root, self.root, ['/Game/' + 'x' * 33000])

    def test_failed_cook_chunk_never_writes_a_receipt(self):
        engine, sdk, _ = self.package_fixture()
        # Remove the fixture's output so the fresh-workspace gate passes.
        cooked = sdk / 'Saved/Cooked/WindowsNoEditor'
        cooked.rename(sdk / 'Saved/fixture')
        commands = [['fake', 'first'], ['fake', 'second']]
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'cook_commands', return_value=commands):
                with patch.object(builder, 'run', side_effect=[None, builder.subprocess.CalledProcessError(1, 'fake')]):
                    with self.assertRaises(builder.subprocess.CalledProcessError):
                        builder.cook(engine, sdk, self.mod)
        self.assertFalse((sdk / builder.COOK_RECEIPT).exists())

    def test_zero_exit_without_cooked_assets_does_not_create_receipt(self):
        self.write_state(self.root)
        engine_fixture(self.root, self.lock['engine'])
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run'):
                with self.assertRaises(ValueError):
                    builder.cook(self.root, self.root, self.mod)
        self.assertFalse((self.root / builder.COOK_RECEIPT).exists())

    def test_package_rejects_modified_cook_outputs_or_engine(self):
        engine, sdk, output = self.package_fixture()
        receipt = {'engine': builder.workspace.engine_identity(engine, self.lock['engine'], 'Win64'),
                   'files': [{'path': rel, 'sha256': builder.file_hash(path)}
                             for path, rel in builder.cooked_inventory(sdk, self.mod)]}
        for changed in ['files', 'engine']:
            with self.subTest(changed=changed):
                invalid = dict(receipt, **{changed: [] if changed == 'files' else {}})
                builder.workspace.write_json(sdk / builder.COOK_RECEIPT, invalid)
                with patch.object(builder, 'os', SimpleNamespace(name='nt')):
                    with patch.object(builder, 'run') as run:
                        with self.assertRaisesRegex(ValueError, 'Cook receipt'):
                            builder.package(engine, sdk, output, self.lock, self.mod)
                        run.assert_not_called()
                self.assertFalse(output.exists())

    def test_cook_refuses_previous_output(self):
        self.write_state(self.root)
        (self.root / 'Saved/Cooked/WindowsNoEditor').mkdir(parents=True)
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run') as run:
                with self.assertRaises(ValueError):
                    builder.cook(self.root, self.root, self.mod)
                run.assert_not_called()

    def test_cook_refuses_stale_receipt_even_when_output_was_removed(self):
        self.write_state(self.root)
        (self.root / builder.COOK_RECEIPT).write_text('{}')
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'Clean cook required'):
                    builder.cook(self.root, self.root, self.mod)
                run.assert_not_called()

    def test_cook_refuses_previous_generated_config(self):
        self.write_state(self.root)
        (self.root / 'Saved/BuilderCook').mkdir(parents=True)
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'Clean cook required'):
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
        engine = engine_fixture(self.root / 'engine', self.lock['engine'])
        self.write_state(sdk)
        return engine, sdk, self.root / 'dist'

    def write_state(self, sdk):
        builder.workspace.write_json(sdk / builder.workspace.STATE, {
            'mod': self.mod, 'lock': self.lock, 'inputs': []
        })

    def test_package_manifest_and_mount(self):
        engine, sdk, output = self.package_fixture()
        unrelated = sdk / 'Saved/Cooked/WindowsNoEditor/TBL/Content/Mods/Other/Other.uasset'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b'not this mod')
        receipt = {
            'verification': 'cook_command_returned_zero',
            'engine': builder.workspace.engine_identity(engine, self.lock['engine'], 'Win64'),
            'files': [{'path': rel, 'sha256': builder.file_hash(path)}
                      for path, rel in builder.cooked_inventory(sdk, self.mod)],
        }
        builder.workspace.write_json(sdk / builder.COOK_RECEIPT, receipt)

        def fake_run(args, log):
            Path(log).write_text('fake tool output')
            if any(str(arg).startswith('-Create=') for arg in args):
                Path(args[1]).write_bytes(b'fake pak')

        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run', side_effect=fake_run) as run:
                builder.package(engine, sdk, output, self.lock, self.mod)
        self.assertEqual(run.call_count, 3)
        response = (output / 'pak-inputs.txt').read_text()
        self.assertNotIn('Other', response)
        self.assertIn('"../../../TBL/Content/Mods/AgMods/ExampleMod/Test.uasset"', response)
        self.assertTrue((output / 'ExampleMod.pak').exists())
        self.assertTrue((output / 'ExampleMod.pak.sha256').exists())
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['prepared_inputs']['mod'], self.mod)
        self.assertEqual(manifest['cook'], receipt)
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
