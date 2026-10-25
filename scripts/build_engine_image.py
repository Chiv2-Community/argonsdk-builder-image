#!/usr/bin/env python3
"""Build a local Linux UE 4.25-plus image from an authorized pinned Git archive."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import engine_tools

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Authorized local UE Git checkout')
    parser.add_argument('--context', required=True, type=Path, help='New build context on a large filesystem')
    parser.add_argument('--base-image', required=True)
    parser.add_argument('--tag', default='argonsdk-ue4.25-plus:local')
    args = parser.parse_args()
    pin = json.loads((ROOT / 'build-lock.json').read_text(encoding='utf-8'))['engine']
    engine_tools.validate_pin(pin)
    # Archive committed files, never copy user work, Git credentials, or downloaded binaries.
    data = subprocess.check_output(['git', '-C', str(args.source), 'show',
                                    f'{pin["commit"]}:Engine/Build/Build.version'], text=True)
    version = json.loads(data)
    if (version.get('BranchName') != pin['build_branch'] or version.get('MajorVersion') != 4
            or version.get('MinorVersion') != 25):
        raise ValueError('Pinned source does not identify UE 4.25-plus')
    context = args.context.resolve()
    context.mkdir(parents=True, exist_ok=False)
    subprocess.run(['git', '-C', str(args.source), 'archive', '--format=tar',
                    f'--output={context / "source.tar"}', pin['commit']], check=True)
    shutil.copy2(ROOT / 'build-lock.json', context)
    shutil.copy2(ROOT / 'Dockerfile.engine', context / 'Dockerfile')
    for name in ['engine_tools.py', 'build-engine.sh', 'sync-mono-trust.cs']:
        shutil.copy2(ROOT / 'scripts' / name, context)
    subprocess.run(['docker', 'build', '--progress=plain', '--build-arg',
                    f'ENGINE_BUILD_BASE={args.base_image}', '--tag', args.tag, str(context)], check=True)


if __name__ == '__main__':
    main()
