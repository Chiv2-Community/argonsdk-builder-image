import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import windows_container_probe as probe


class WindowsContainerTests(unittest.TestCase):
    def test_runtime_shell_does_not_depend_on_replaced_path(self):
        recipe = (Path(__file__).resolve().parents[1] / 'Dockerfile.windows-cooker-probe').read_text()
        shell = next(line for line in recipe.splitlines() if line.startswith('SHELL '))
        args = json.loads(shell.removeprefix('SHELL '))
        self.assertEqual(args[0], r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
        path = next(line for line in recipe.splitlines() if line.startswith('ENV PATH='))
        self.assertIn(r'C:\Windows\System32\WindowsPowerShell\v1.0', path)

    def test_prerequisite_script_runs_before_large_engine_layer(self):
        recipe = (Path(__file__).resolve().parents[1] / 'Dockerfile.windows-cooker-probe').read_text()
        run = next(line for line in recipe.splitlines() if line.startswith('RUN ['))
        args = json.loads(run.removeprefix('RUN '))
        self.assertEqual(args[-2:], ['-File', r'C:\image-prerequisites\install-windows-cooker-runtime.ps1'])
        self.assertLess(recipe.index(run), recipe.index('COPY engine/'))

    def test_failed_stage_stops_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(probe.os.environ, UE_ROOT='engine', ARGON_SDK_ROOT='template'), \
                 patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 9)) as run:
                with self.assertRaisesRegex(RuntimeError, 'prepare failed'):
                    probe.validate('descriptor.json', root / 'diagnostics', root / 'job')
            self.assertEqual(run.call_count, 1)
            report = json.loads((root / 'diagnostics/result.json').read_text())
            self.assertEqual(report['verification'], 'not_completed')
            self.assertEqual(report['stages'], [{'name': 'prepare', 'exit_code': 9}])

    def test_success_requires_actual_cook_and_exports_no_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {'cook': {'verification': 'cook_command_returned_zero',
                                 'requested_packages': ['/Game/Mods/Test/Asset']},
                        'engine': {'commit': 'e' * 40}, 'files': [{'path': 'Asset.uasset'}],
                        'pak_sha256': 'a' * 64}

            def run(command, **kwargs):
                if 'package' in command:
                    dist = root / 'job/dist'
                    dist.mkdir(parents=True)
                    (dist / 'manifest.json').write_text(json.dumps(manifest))
                    (dist / 'licensed.pak').write_bytes(b'not for upload')
                return subprocess.CompletedProcess(command, 0)

            with patch.dict(probe.os.environ, UE_ROOT='engine', ARGON_SDK_ROOT='template'), \
                 patch.object(probe.subprocess, 'run', side_effect=run) as calls:
                probe.validate('descriptor.json', root / 'diagnostics', root / 'job')
            report = json.loads((root / 'diagnostics/result.json').read_text())
            self.assertEqual(report['verification'], 'windows_container_source_cook_and_package_passed')
            self.assertEqual(report['requested_packages'], 1)
            self.assertEqual({p.name for p in (root / 'diagnostics').iterdir()},
                             {'prepare.log', 'cook.log', 'package.log', 'result.json'})
            self.assertEqual(calls.call_count, 3)
            self.assertNotIn('build-editor', str(calls.call_args_list))


if __name__ == '__main__':
    unittest.main()
