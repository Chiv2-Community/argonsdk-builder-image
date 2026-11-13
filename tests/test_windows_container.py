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
