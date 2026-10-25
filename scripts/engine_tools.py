"""UE 4.25-plus source/image identity checks and build receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

RECEIPT = '.builder-engine.json'
BRANCH = '++UE4+Release-4.25Plus'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_pin(pin):
    if pin['branch'] != '4.25-plus' or pin['build_branch'] != BRANCH:
        raise ValueError('This builder requires UE 4.25-plus')
    if not re.fullmatch('[0-9a-f]{40}', pin['commit']):
        raise ValueError('UE 4.25-plus requires a full pinned source commit')


def version(root):
    data = json.loads((Path(root) / 'Engine/Build/Build.version').read_text(encoding='utf-8'))
    if data.get('MajorVersion') != 4 or data.get('MinorVersion') != 25 or data.get('BranchName') != BRANCH:
        raise ValueError('Engine Build.version must identify UE 4.25-plus, not stock UE 4.25')
    return data


def identity(root, pin, platform=None):
    validate_pin(pin)
    root = Path(root).resolve()
    build_version = version(root)
    # SetupToolchain creates .git/ue4-sdks in archive builds; that is not a Git checkout.
    if (root / '.git').is_file() or (root / '.git/HEAD').is_file():
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                         '--untracked-files=no'], text=True).strip()
        if commit != pin['commit'] or dirty:
            raise ValueError('Engine source must match the clean pinned UE 4.25-plus commit')
        if platform is not None and not all((root / rel).is_file() for rel in tool_files(platform)):
            raise ValueError('Pinned source exists but the required engine tools have not been built')
        return {'branch': pin['branch'], 'commit': commit, 'verification': 'git_metadata',
                'build_version': build_version}
    receipt = json.loads((root / RECEIPT).read_text(encoding='utf-8'))
    if receipt['source'] != pin:
        raise ValueError('Engine image receipt does not match the pinned UE 4.25-plus source')
    if platform is not None and receipt['platform'] != platform:
        raise ValueError('Engine receipt platform does not match the requested toolchain')
    for rel, expected in receipt['files'].items():
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or digest(path) != expected:
            raise ValueError(f'Engine receipt file mismatch: {rel}')
    required = tool_files(receipt['platform'])
    if not set(required).issubset(receipt['files']):
        raise ValueError('Engine receipt is missing required tool identities')
    return {'branch': pin['branch'], 'commit': pin['commit'], 'verification': 'build_receipt_hashes',
            'build_version': build_version, 'receipt': receipt}


def tool_files(platform):
    if platform == 'Linux':
        names = ['UE4Editor', 'ShaderCompileWorker', 'UnrealPak']
    elif platform == 'Win64':
        names = ['UE4Editor-Cmd.exe', 'ShaderCompileWorker.exe', 'UnrealPak.exe']
    else:
        raise ValueError('Unsupported engine receipt platform')
    return ['Engine/Build/Build.version', *[f'Engine/Binaries/{platform}/{name}' for name in names]]


def write_receipt(root, pin, platform, archive):
    validate_pin(pin)
    version(root)
    root = Path(root)
    receipt = {'schema_version': 1, 'source': pin, 'platform': platform,
               'source_archive_sha256': digest(archive),
               'files': {rel: digest(root / rel) for rel in tool_files(platform)}}
    patches = root / '.builder-transport.json'
    if patches.exists():
        receipt['transport_patches'] = json.loads(patches.read_text(encoding='utf-8'))
    (root / RECEIPT).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def https_transport(root):
    """Upgrade pinned CDN URLs in the isolated build tree; record every change."""
    root = Path(root)
    paths = [root / 'Engine/Build/Commit.gitdeps.xml',
             root / 'Engine/Build/BatchFiles/Linux/SetupToolchain.sh']
    changes = []
    for path in paths:
        before = path.read_bytes()
        after = before.replace(b'http://cdn.unrealengine.com', b'https://cdn.unrealengine.com')
        if after != before:
            changes.append({'path': path.relative_to(root).as_posix(),
                            'before': hashlib.sha256(before).hexdigest(),
                            'after': hashlib.sha256(after).hexdigest()})
            path.write_bytes(after)
    (root / '.builder-transport.json').write_text(json.dumps(changes, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'https-transport', 'receipt'])
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--platform', choices=['Linux', 'Win64'])
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if args.command == 'https-transport':
        https_transport(args.engine)
        return
    if args.lock is None:
        parser.error('--lock is required')
    pin = json.loads(args.lock.read_text(encoding='utf-8'))['engine']
    if args.command == 'check':
        print(json.dumps(identity(args.engine, pin, args.platform), indent=2))
    else:
        if args.platform is None or args.archive is None:
            parser.error('--platform and --archive are required for a receipt')
        write_receipt(args.engine, pin, args.platform, args.archive)


if __name__ == '__main__':
    main()
