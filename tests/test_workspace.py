"""Real local Git/filesystem tests. No Unreal or network access required."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import workspace
import builder
import engine_tools
import sdk_tools
from fixtures import engine_fixture


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                   stderr=subprocess.STDOUT).strip()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='argon fixture ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sdk = self.repository('SDK template', {'TBL.uproject': '{}', 'Content/Base.uasset': 'base'})
        self.source = self.repository('mod source', {'Content/Test.uasset': 'asset'})
        self.lock = {
            'argon_sdk': {'repository': 'https://example.invalid/sdk.git', 'commit': git(self.sdk, 'rev-parse', 'HEAD')},
            'engine': {'branch': '4.25-plus', 'commit': 'a' * 40, 'build_branch': engine_tools.BRANCH},
        }
        self.mod = workspace.descriptor({
            'name': 'ExampleMod', 'repository': 'https://example.invalid/mod.git',
            'commit': git(self.source, 'rev-parse', 'HEAD'), 'content_path': 'Content',
            'package_path': 'Mods/AgMods/ExampleMod',
        })

    def repository(self, name, files):
        root = self.root / name
        root.mkdir()
        git(root, 'init', '-b', 'main')
        for rel, value in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        git(root, 'add', '.')
        git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
        return root

    def no_checkout(self, *args):
        self.fail('Template + mounted source must not access the network')

    def patched_sdk(self):
        sdk = self.repository('patched SDK', {
            'TBL.uproject': '{}', 'Content/Base.uasset': 'base',
            sdk_tools.BUILD_RULES: 'PublicDependencyModuleNames.AddRange(new string[] {\n            "Engine",\n});\n',
        })
        commit = git(sdk, 'rev-parse', 'HEAD')
        sdk_tools.apply_linux_rhi(sdk, commit)
        return sdk, commit

    def test_approved_sdk_patch_is_explicit_and_copied_into_provenance(self):
        sdk, commit = self.patched_sdk()
        identity = workspace.verified_sdk(sdk, commit)
        self.assertTrue(identity['dirty'])
        self.assertEqual(identity['verification'], 'git_commit_with_verified_build_rule_patch')
        self.assertEqual(identity['build_rule_patch']['source_commit'], commit)
        self.assertEqual(sdk_tools.apply_linux_rhi(sdk, commit), identity)
        lock = dict(self.lock, argon_sdk=dict(self.lock['argon_sdk'], commit=commit))
        state = workspace.prepare(lock, self.root / 'patched job', self.mod, self.no_checkout,
                                  template=sdk, local_source=self.source)
        self.assertEqual(state['sdk'], identity)
        self.assertTrue((self.root / 'patched job/ArgonSDK' / sdk_tools.RECEIPT).is_file())

    def test_sdk_patch_does_not_authorize_other_source_changes(self):
        sdk, commit = self.patched_sdk()
        (sdk / 'TBL.uproject').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'outside the approved'):
            workspace.verified_sdk(sdk, commit)

    def test_modified_sdk_patch_or_receipt_is_rejected(self):
        sdk, commit = self.patched_sdk()
        rules = sdk / sdk_tools.BUILD_RULES
        after = rules.read_bytes()
        rules.write_bytes(after + b'// extra change\n')
        with self.assertRaisesRegex(ValueError, 'approved transformation'):
            workspace.verified_sdk(sdk, commit)
        rules.write_bytes(after)
        receipt = sdk / sdk_tools.RECEIPT
        data = json.loads(receipt.read_text())
        data['before_sha256'] = '0' * 64
        workspace.write_json(receipt, data)
        with self.assertRaisesRegex(ValueError, 'approved transformation'):
            workspace.verified_sdk(sdk, commit)

    def test_unexpected_sdk_build_rules_are_not_patched(self):
        for before in [b'no Engine dependency', b'            "Engine",\n            "RHI",']:
            with self.subTest(before=before):
                with self.assertRaises(ValueError):
                    sdk_tools.add_rhi(before)

    def test_rhi_patch_preserves_committed_line_endings(self):
        for newline in [b'\n', b'\r\n']:
            before = b'            "Engine",' + newline
            after = sdk_tools.add_rhi(before)
            self.assertEqual(after, before + b'            "RHI",' + newline)

    def prepare(self, job='job', **kwargs):
        return workspace.prepare(self.lock, self.root / job, self.mod, self.no_checkout,
                                 template=self.sdk, local_source=self.source, **kwargs)

    def test_real_git_identity_and_mod_receipt(self):
        state = self.prepare()
        self.assertEqual(state['sdk']['commit'], self.lock['argon_sdk']['commit'])
        self.assertEqual(state['inputs'][0]['git']['commit'], self.mod['commit'])
        self.assertEqual(state['inputs'][0]['verification'], 'git_commit_and_clean_tree')
        self.assertEqual(workspace.verify_inputs(self.root / 'job/ArgonSDK', self.mod, self.lock), state)

    def test_cli_prepares_template_and_source_without_network(self):
        lockfile, modfile = self.root / 'lock.json', self.root / 'mod.json'
        workspace.write_json(lockfile, self.lock)
        workspace.write_json(modfile, self.mod)
        subprocess.run([sys.executable, str(ROOT / 'scripts/builder.py'), '--lock', str(lockfile),
                        '--mod-config', str(modfile), 'prepare', '--workspace', str(self.root / 'cli job'),
                        '--sdk-template', str(self.sdk), '--mod-source', str(self.source)], check=True)
        state = json.loads((self.root / 'cli job/ArgonSDK' / workspace.STATE).read_text())
        self.assertEqual(state['inputs'][0]['git']['commit'], self.mod['commit'])

    def test_content_path_with_spaces_and_flat_namespace(self):
        source = self.root / 'plain source'
        (source / 'Mod Content').mkdir(parents=True)
        (source / 'Mod Content/Map.umap').write_text('map')
        self.mod = workspace.descriptor(dict(self.mod, content_path='Mod Content', package_path='Mods/ExampleMod'))
        workspace.prepare(self.lock, self.root / 'job', self.mod, self.no_checkout,
                          template=self.sdk, local_source=source)
        self.assertTrue((self.root / 'job/ArgonSDK/Content/Mods/ExampleMod/Map.umap').exists())

    @unittest.skipIf(sys.platform == 'win32', 'Windows cannot create these fixture names')
    def test_content_names_must_be_portable_to_windows(self):
        for name in ['a:b.uasset', 'a\\b.uasset', 'a?.uasset', 'CON.uasset', 'trailing.', 'trailing ']:
            with self.subTest(name=name):
                path = self.root / 'bad names'
                path.mkdir(exist_ok=True)
                item = path / name
                item.write_bytes(b'asset')
                with self.assertRaisesRegex(ValueError, 'Nonportable'):
                    workspace.snapshot(path)
                item.unlink()

    def test_portable_hidden_and_unicode_content_names(self):
        path = self.root / 'portable'
        path.mkdir()
        for name in ['.gitignore', 'Material + Detail.uasset', 'Texture_é.uasset']:
            (path / name).write_bytes(b'asset')
        self.assertEqual(len(workspace.snapshot(path)), 3)

    def test_two_jobs_leave_source_and_template_unchanged(self):
        before = workspace.snapshot(self.sdk / 'Content')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.prepare, ['job 1', 'job 2']))
        copied = self.root / 'job 1/ArgonSDK/Content/Mods/AgMods/ExampleMod/Test.uasset'
        copied.write_text('changed by first job')
        self.assertEqual((self.source / 'Content/Test.uasset').read_text(), 'asset')
        self.assertEqual((self.root / 'job 2/ArgonSDK/Content/Mods/AgMods/ExampleMod/Test.uasset').read_text(), 'asset')
        self.assertEqual(workspace.snapshot(self.sdk / 'Content'), before)
        self.assertFalse(workspace.git_identity(self.sdk)['dirty'])

    def test_same_workspace_is_claimed_once(self):
        def attempt(_):
            try:
                self.prepare()
                return True
            except (ValueError, FileExistsError):
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), [False, True])

    def test_template_cache_is_not_copied(self):
        git(self.sdk, 'config', 'core.excludesFile', str(self.root / 'ignore'))
        (self.root / 'ignore').write_text('Saved/\nIntermediate/\n')
        (self.sdk / 'Saved').mkdir()
        (self.sdk / 'Saved/stale.pak').write_text('old')
        self.prepare()
        self.assertFalse((self.root / 'job/ArgonSDK/Saved').exists())
        self.assertFalse((self.root / 'job/ArgonSDK/.git').exists())

    def test_mutated_content_is_rejected(self):
        self.prepare()
        content = self.root / 'job/ArgonSDK/Content/Mods/AgMods/ExampleMod/Test.uasset'
        content.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'content changed'):
            workspace.verify_inputs(self.root / 'job/ArgonSDK', self.mod, self.lock)

    def test_descriptor_and_lock_mismatch_are_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'Descriptor/lock'):
            workspace.verify_inputs(self.root / 'job/ArgonSDK', dict(self.mod, name='Other'))
        with self.assertRaisesRegex(ValueError, 'Descriptor/lock'):
            workspace.verify_inputs(self.root / 'job/ArgonSDK', self.mod, {})

    def test_dirty_mounted_checkout_is_rejected(self):
        (self.source / 'Content/Test.uasset').write_text('uncommitted')
        with self.assertRaisesRegex(ValueError, 'clean pinned commit'):
            self.prepare()
        # Failed preparation is not silently reused; a new workspace is required.
        with self.assertRaises((ValueError, FileExistsError)):
            self.prepare()

    def test_template_revision_mismatch_is_rejected(self):
        self.lock['argon_sdk']['commit'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'pinned SDK revision'):
            self.prepare()

    def test_destination_collision_with_existing_sdk_namespace_is_rejected(self):
        path = self.sdk / 'Content/Mods/AgMods/examplemod'
        path.mkdir(parents=True)
        (path / 'Existing.uasset').write_text('existing')
        git(self.sdk, 'add', '.')
        git(self.sdk, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'existing mod')
        self.lock['argon_sdk']['commit'] = git(self.sdk, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.prepare()

    def test_sdk_submodules_are_checked_at_recorded_commits(self):
        git(self.sdk, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(self.source), 'External')
        git(self.sdk, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-am', 'add submodule')
        self.lock['argon_sdk']['commit'] = git(self.sdk, 'rev-parse', 'HEAD')
        state = self.prepare()
        self.assertEqual(len(state['sdk']['submodules']), 1)
        self.assertTrue(state['sdk']['submodules'][0].startswith(' '))

    def test_plain_mount_is_identified_by_content_not_claimed_commit(self):
        source = self.root / 'plain'
        (source / 'Content').mkdir(parents=True)
        (source / 'Content/Test.uasset').write_text('local asset')
        state = workspace.prepare(self.lock, self.root / 'job', self.mod, self.no_checkout,
                                  template=self.sdk, local_source=source)
        self.assertIsNone(state['inputs'][0]['git'])
        self.assertEqual(state['inputs'][0]['verification'], 'local_content_hashes_only')

    def test_dependency_inputs_are_copied_and_snapshotted(self):
        dep = dict(self.mod, name='Shared', package_path='Mods/Shared')
        dep.pop('dependencies')
        self.mod = workspace.descriptor(dict(self.mod, dependencies=[dep]))
        def clone(repo, commit, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            git(dest.parent, 'clone', '--no-hardlinks', str(self.source), str(dest))
        state = workspace.prepare(self.lock, self.root / 'job', self.mod, clone,
                                  template=self.sdk, local_source=self.source)
        self.assertEqual(len(state['inputs']), 2)
        self.assertTrue((self.root / 'job/ArgonSDK/Content/Mods/Shared/Test.uasset').exists())
        workspace.verify_inputs(self.root / 'job/ArgonSDK', self.mod, self.lock)

    def test_namespace_overlap_is_rejected_case_insensitively(self):
        for path in ['Mods/AgMods/ExampleMod', 'Mods/AgMods', 'Mods/AgMods/examplemod/Child']:
            with self.subTest(path=path):
                dep = dict(self.mod, name='Shared', package_path=path)
                dep.pop('dependencies')
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    workspace.descriptor(dict(self.mod, dependencies=[dep]))

    def test_unknown_schema_and_fields_are_rejected(self):
        for changed in [{'schema_version': 2}, {'schema_version': True}, {'typo': 'value'}]:
            with self.assertRaises(ValueError):
                workspace.descriptor(dict(self.mod, **changed))

    def test_credentials_and_reserved_names_are_rejected(self):
        for change in [{'repository': 'https://user:token@example.invalid/mod.git'},
                       {'name': 'CON'}, {'content_path': 'Content/NUL.txt'},
                       {'package_path': 'Mods/AUX'}, {'name': 'Name.'}]:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    workspace.descriptor(dict(self.mod, **change))

    def test_workspace_must_not_overlap_inputs(self):
        with self.assertRaisesRegex(ValueError, 'overlap'):
            workspace.prepare(self.lock, self.sdk / 'job', self.mod, self.no_checkout,
                              template=self.sdk, local_source=self.source)

    def test_image_reference_is_explicitly_unattested(self):
        reference = 'registry.invalid/builder@sha256:' + '1' * 64
        state = self.prepare(image_reference=reference)
        self.assertEqual(state['image']['reference'], reference)
        self.assertEqual(state['image']['verification'], 'caller_supplied_not_runtime_attested')
        with self.assertRaises(ValueError):
            self.prepare('other', image_reference='builder:latest')

    @unittest.skipIf(sys.platform == 'win32', 'Requires unprivileged symlink support')
    def test_symlinked_content_and_case_collision_are_rejected(self):
        plain = self.root / 'plain'
        plain.mkdir()
        (plain / 'Content').symlink_to(self.source / 'Content', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Links'):
            workspace.prepare(self.lock, self.root / 'job', self.mod, self.no_checkout,
                              template=self.sdk, local_source=plain)
        collision = self.root / 'collision'
        collision.mkdir()
        (collision / 'Asset.uasset').write_text('one')
        (collision / 'asset.uasset').write_text('two')
        with self.assertRaisesRegex(ValueError, 'collision'):
            workspace.snapshot(collision)

    def test_engine_without_git_or_receipt_is_rejected(self):
        engine = self.root / 'engine'
        (engine / 'Engine/Build').mkdir(parents=True)
        (engine / 'Engine/Build/Build.version').write_text(json.dumps({
            'MajorVersion': 4, 'MinorVersion': 25, 'BranchName': engine_tools.BRANCH}))
        with self.assertRaises(FileNotFoundError):
            workspace.engine_identity(engine, self.lock['engine'])

    def test_engine_commit_mismatch_is_rejected(self):
        engine = self.repository('engine', {'Engine/Build/Build.version': json.dumps({
            'MajorVersion': 4, 'MinorVersion': 25, 'BranchName': engine_tools.BRANCH})})
        with self.assertRaisesRegex(ValueError, 'pinned UE 4.25-plus'):
            workspace.engine_identity(engine, self.lock['engine'])

    def package_fixture(self):
        self.prepare()
        sdk = self.root / 'job/ArgonSDK'
        cooked = sdk / 'Saved/Cooked/WindowsNoEditor/TBL/Content'
        own = cooked / self.mod['package_path']
        own.mkdir(parents=True)
        (own / 'Test.uasset').write_text('cooked asset')
        (own / 'Test.uexp').write_text('compiled')
        other = cooked / 'Mods/Other'
        other.mkdir(parents=True)
        (other / 'Other.uasset').write_text('dependency must not be packed')
        engine = engine_fixture(self.root / 'engine', self.lock['engine'])
        return engine, sdk, self.root / 'output'

    def test_packaging_excludes_other_cooked_namespaces(self):
        engine, sdk, output = self.package_fixture()
        def run(args, log):
            Path(log).write_text('fake UnrealPak')
            if any(str(arg).startswith('-Create=') for arg in args):
                Path(args[1]).write_bytes(b'pak')
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run', side_effect=run):
                builder.package(engine, sdk, output, self.lock, self.mod)
        response = (output / 'pak-inputs.txt').read_text()
        self.assertNotIn('Other', response)
        self.assertIn('Mods/AgMods/ExampleMod/Test.uasset', response)

    def test_failed_pak_test_does_not_emit_success_manifest(self):
        engine, sdk, output = self.package_fixture()
        def run(args, log):
            if '-Test' in args:
                raise subprocess.CalledProcessError(1, args)
            Path(log).write_text('fake UnrealPak')
            Path(args[1]).write_bytes(b'bad pak')
        with patch.object(builder, 'os', SimpleNamespace(name='nt')):
            with patch.object(builder, 'run', side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.package(engine, sdk, output, self.lock, self.mod)
        self.assertFalse((output / 'manifest.json').exists())
        self.assertFalse((output / 'ExampleMod.pak.sha256').exists())


if __name__ == '__main__':
    unittest.main()
