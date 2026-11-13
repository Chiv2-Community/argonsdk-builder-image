#!/usr/bin/env python3
"""Cook source using the image's precompiled SDK; export diagnostics only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

import builder
import workspace


def validate(descriptor, output, job=Path('C:/work/job')):
    sdk = Path(job) / 'ArgonSDK'
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    engine = Path(os.environ['UE_ROOT'])
    cli = builder.ROOT / 'scripts/builder.py'
    report = {'verification': 'not_completed', 'container_hostname': socket.gethostname(),
              'game_runtime_validation': 'not_run', 'stages': []}
    try:
        commands = [
            ('prepare', ['--mod-config', descriptor, 'prepare', '--workspace', str(sdk.parent),
                         '--sdk-template', os.environ['ARGON_SDK_ROOT']]),
            ('cook', ['--mod-config', descriptor, 'cook', '--engine', str(engine), '--sdk', str(sdk)]),
            ('package', ['--mod-config', descriptor, 'package', '--engine', str(engine),
                         '--sdk', str(sdk), '--output', str(sdk.parent / 'dist')]),
        ]
        for stage, args in commands:
            with (output / (stage + '.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run(['python', str(cli), *args], stdout=log,
                                        stderr=subprocess.STDOUT)
            report['stages'].append({'name': stage, 'exit_code': result.returncode})
            if result.returncode:
                raise RuntimeError(f'{stage} failed: {result.returncode}')
        manifest = json.loads((sdk.parent / 'dist/manifest.json').read_text(encoding='utf-8'))
        if manifest['cook']['verification'] != 'cook_command_returned_zero':
            raise ValueError('Actual source cooking is required')
        report.update(verification='windows_container_source_cook_and_package_passed',
                      engine_commit=manifest['engine']['commit'],
                      requested_packages=len(manifest['cook']['requested_packages']),
                      cooked_files=len(manifest['files']), pak_sha256=manifest['pak_sha256'])
    finally:
        workspace.write_json(output / 'result.json', report)
        logs = sdk / 'Saved/Logs'
        if logs.is_dir():
            for log in logs.glob('*.log'):
                if log.is_file() and not log.is_symlink():
                    shutil.copy2(log, output / ('editor-' + log.name))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', required=True)
    parser.add_argument('--output', default='C:/work/diagnostics')
    args = parser.parse_args()
    validate(args.descriptor, args.output)
