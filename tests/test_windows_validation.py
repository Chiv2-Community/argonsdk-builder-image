"""Engine-free orchestration checks; not a substitute for a real cook."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required')
class WindowsValidationTests(unittest.TestCase):
    def probe(self, fail):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'engine/.git').mkdir(parents=True)
            (root / 'descriptor.json').write_text('{}')
            wrapper = root / 'probe.ps1'
            wrapper.write_text('''
param([string]$Root, [string]$Production, [string]$Fail)
$ErrorActionPreference = 'Stop'
$env:RUNNER_TEMP = $Root
function global:python {
    $stage = 'check'
    foreach ($candidate in @('prepare', 'build-editor', 'cook', 'package')) {
        if ($args -contains $candidate) { $stage = $candidate }
    }
    Add-Content "$Root/stages.txt" $stage
    if ($stage -eq $Fail) { $global:LASTEXITCODE = 23; return }
    if ($stage -eq 'package') {
        New-Item -ItemType Directory -Path "$Root/work/dist" -Force | Out-Null
        @{cook=@{verification='cook_command_returned_zero'}; engine=@{commit='test'};
          files=@(@{}); pak_sha256='test'} | ConvertTo-Json -Depth 4 |
            Set-Content "$Root/work/dist/manifest.json"
    }
    $global:LASTEXITCODE = 0
}
& $Production -Engine "$Root/engine" -Workspace "$Root/work" -Descriptor "$Root/descriptor.json"
''')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(wrapper),
                                     '-Root', str(root), '-Production',
                                     str(ROOT / 'scripts/validate-windows-builder.ps1'),
                                     '-Fail', fail], capture_output=True, text=True)
            stages = (root / 'stages.txt').read_text().splitlines()
            summary = root / 'windows-builder-validation.json'
            data = json.loads(summary.read_text(encoding='utf-8-sig')) if summary.exists() else None
            self.assertTrue((root / 'ue-validation-git-metadata').is_dir())
            return result, stages, data

    def test_success_requires_all_production_stages(self):
        result, stages, summary = self.probe('none')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(stages, ['check', 'prepare', 'build-editor', 'cook', 'package'])
        self.assertEqual(summary['verification'], 'native_windows_source_cook_and_package_passed')
        self.assertEqual(summary['container_validation'], 'not_run')
        self.assertEqual(summary['game_runtime_validation'], 'not_run')

    def test_failure_stops_before_any_later_stage_or_success_summary(self):
        order = ['check', 'prepare', 'build-editor', 'cook', 'package']
        for stage in order:
            with self.subTest(stage=stage):
                result, stages, summary = self.probe(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(stages, order[:order.index(stage) + 1])
                self.assertIsNone(summary)
