#!/usr/bin/env python3
"""Pinned SDK preparation and Windows content cooking. No publication commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import workspace
import engine_tools

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SUFFIXES = {'.uasset', '.umap', '.uexp', '.ubulk'}
COOK_RECEIPT = '.builder-cook.json'
MAX_COOK_PACKAGES = 250
MAX_COOK_COMMAND_UNITS = 30000  # Leave headroom below Windows' 32767 UTF-16 limit.


def cook_packages(sdk, mod):
    content = Path(sdk).resolve() / 'Content'
    source = workspace.directory_within(sdk, 'Content/' + mod['package_path'])
    packages = []
    for path in workspace.checked_tree(source):
        if not path.is_file() or path.suffix not in {'.uasset', '.umap'}:
            continue
        package = '/Game/' + path.relative_to(content).with_suffix('').as_posix()
        # UE long package names forbid these characters; '+' also separates Map entries.
        if any(c in package for c in '\\:*?"<>|\' ,.&!~\n\r\t@#+'):
            raise ValueError(f'Invalid Unreal package name: {package}')
        packages.append(package)
    if not packages or len({p.casefold() for p in packages}) != len(packages):
        raise ValueError('Cook requires nonempty, unique source package names')
    return sorted(packages)


def cook_commands(engine, sdk, packages):
    base = [tool(engine, 'UE4Editor-Cmd'), Path(sdk) / 'TBL.uproject', '-run=Cook',
            '-TargetPlatform=WindowsNoEditor', '-cooksinglepackage', '-skipeditorcontent',
            '-unattended', '-nop4', '-UTF8Output', '-NullRHI',
            f'-DefGameIni={Path(sdk) / "Saved/BuilderCook/DefaultGame.ini"}',
            '-ini:Game:[/Script/UnrealEd.ProjectPackagingSettings]:BlueprintNativizationMethod=Disabled']

    def command(batch, continuation=False):
        # Only later chunks may reuse output created earlier in this fresh job.
        return [*base, '-Map=' + '+'.join(batch), *(['-iterate'] if continuation else [])]

    def fits(batch):
        text = subprocess.list2cmdline([str(arg) for arg in command(batch, True)])
        return len(batch) <= MAX_COOK_PACKAGES and len(text.encode('utf-16-le')) // 2 < MAX_COOK_COMMAND_UNITS

    commands, batch = [], []
    for package in packages:
        if not fits([*batch, package]):
            if not batch:
                raise ValueError('Cook command exceeds the Windows command-line limit')
            commands.append(command(batch, bool(commands)))
            batch = []
            if not fits([package]):
                raise ValueError('Cook command exceeds the Windows command-line limit')
        batch.append(package)
    if batch:
        commands.append(command(batch, bool(commands)))
    return commands


def cook_game_config(sdk):
    original = workspace.directory_within(sdk, 'Config/DefaultGame.ini')
    before = original.read_bytes() if original.is_file() else b''
    # CookCommandlet reads DirectoriesToAlwaysCook even in single-package mode.
    after = before + b'\n[/Script/UnrealEd.ProjectPackagingSettings]\n!DirectoriesToAlwaysCook=ClearArray\n!MapsToCook=ClearArray\n'
    path = Path(sdk) / 'Saved/BuilderCook/DefaultGame.ini'
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_bytes(after)
    return {'path': 'Saved/BuilderCook/DefaultGame.ini',
            'original_sha256': hashlib.sha256(before).hexdigest(),
            'sha256': hashlib.sha256(after).hexdigest()}


def run(args, log=None):
    args = [str(a) for a in args]
    print(subprocess.list2cmdline(args), flush=True)
    if log is None:
        subprocess.run(args, check=True)
    else:
        with Path(log).open('w', encoding='utf-8') as stream:
            subprocess.run(args, check=True, stdout=stream, stderr=subprocess.STDOUT)


def lockfile(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('argon_sdk', 'engine'):
        if not re.fullmatch('[0-9a-f]{40}', data[key]['commit']):
            raise ValueError(f'Invalid {key} commit')
    engine_tools.validate_pin(data['engine'])
    return data


def mod_config(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return workspace.descriptor(data)


def checkout(repo, commit, dest):
    dest = Path(dest).resolve()
    if dest.exists():
        raise ValueError(f'Refusing to replace existing checkout: {dest}')
    dest.mkdir(parents=True)
    run(['git', '-C', dest, 'init'])
    run(['git', '-C', dest, 'remote', 'add', 'origin', repo])
    run(['git', '-C', dest, 'fetch', '--depth=1', 'origin', commit])
    run(['git', '-C', dest, 'checkout', '--detach', commit])
    # Recorded gitlinks only; never update to remote branch heads.
    run(['git', '-C', dest, 'submodule', 'update', '--init', '--recursive'])


def prepare(lock, directory, mod=None, template=None, local_source=None, image_reference=None):
    return workspace.prepare(lock, directory, mod, checkout, template, local_source, image_reference)


def tool(engine, name):
    engine = Path(engine).resolve()
    if name == 'build':
        return engine / 'Engine/Build/BatchFiles/Build.bat'
    return engine / 'Engine/Binaries/Win64' / f'{name}.exe'


def build_editor(engine, sdk, lock):
    if os.name != 'nt':
        raise ValueError('Windows editor baseline requires a Windows host')
    workspace.engine_identity(engine, lock['engine'], 'Win64')
    run([tool(engine, 'build'), 'TBLEditor', 'Win64', 'Development',
         f'-Project={Path(sdk).resolve() / "TBL.uproject"}', '-WaitMutex', '-NoHotReload'])


def cook(engine, sdk, mod):
    if os.name != 'nt':
        raise ValueError('Windows cooking is not implemented on native Linux')
    sdk = Path(sdk).resolve()
    state = workspace.verify_inputs(sdk, mod)
    cooked = sdk / 'Saved/Cooked/WindowsNoEditor'
    if cooked.exists() or (sdk / COOK_RECEIPT).exists() or (sdk / 'Saved/BuilderCook').exists():
        raise ValueError(f'Clean cook required; use a fresh SDK checkout: {cooked}')
    packages = cook_packages(sdk, mod)
    commands = cook_commands(engine, sdk, packages)
    engine_info = workspace.engine_identity(engine, state['lock']['engine'], 'Win64')
    config = cook_game_config(sdk)
    for command in commands:
        run(command)
        workspace.verify_inputs(sdk, mod)
    workspace.verify_inputs(sdk, mod)
    entries = cooked_inventory(sdk, mod)
    workspace.write_json(sdk / COOK_RECEIPT, {
        'verification': 'cook_command_returned_zero',
        'commands': [[str(arg) for arg in command] for command in commands],
        'requested_packages': packages, 'engine': engine_info,
        'game_config_override': config,
        'files': [{'path': rel, 'sha256': file_hash(path)} for path, rel in entries],
        'editor_sha256': file_hash(tool(engine, 'UE4Editor-Cmd')) if tool(engine, 'UE4Editor-Cmd').is_file() else None,
    })


def inventory(root):
    root = Path(root).resolve()
    entries = []
    for path in workspace.checked_tree(root):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if path.suffix not in PACKAGE_SUFFIXES:
            raise ValueError(f'Unexpected cooked file: {rel}')
        if any(c in str(path) for c in ('"', '\n', '\r')):
            raise ValueError(f'Unsafe response-file path: {path}')
        entries.append((path, rel.as_posix()))
    if not entries:
        raise ValueError('No cooked mod files found')
    return entries


def file_hash(path):
    return workspace.file_hash(path)


def cooked_inventory(sdk, mod):
    source = workspace.directory_within(sdk, 'Content/' + mod['package_path'])
    entries = inventory(workspace.directory_within(sdk, 'Saved/Cooked/WindowsNoEditor/TBL/Content/' + mod['package_path']))
    source_packages = {p.relative_to(source).as_posix() for p in workspace.checked_tree(source)
                       if p.suffix in {'.uasset', '.umap'}}
    cooked_packages = {rel for _, rel in entries if Path(rel).suffix in {'.uasset', '.umap'}}
    if not source_packages or source_packages != cooked_packages:
        raise ValueError('Source/cooked package inventory mismatch; refusing incomplete PAK')
    return entries


def package(engine, sdk, output, lock, mod):
    if os.name != 'nt':
        raise ValueError('Packaging baseline requires Windows UnrealPak')
    sdk, output = Path(sdk).resolve(), Path(output).resolve()
    state = workspace.verify_inputs(sdk, mod, lock)
    engine_info = workspace.engine_identity(engine, lock['engine'], 'Win64')
    entries = cooked_inventory(sdk, mod)
    files = [{'path': rel, 'sha256': file_hash(path)} for path, rel in entries]
    receipt_path = sdk / COOK_RECEIPT
    cook_receipt = (json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists()
                    else {'verification': 'no_cook_receipt'})
    if receipt_path.exists() and (cook_receipt['engine'] != engine_info or cook_receipt['files'] != files):
        raise ValueError('Cook receipt does not match the current engine or cooked files')
    if output.exists():
        raise ValueError('Use a new output directory; existing artifacts are never replaced')
    output.mkdir(parents=True)
    response = output / 'pak-inputs.txt'
    response.write_text(''.join(f'"{path}" "../../../TBL/Content/{mod["package_path"]}/{rel}"\n'
                                for path, rel in entries), encoding='utf-8')
    pak = output / f'{mod["name"]}.pak'
    run([tool(engine, 'UnrealPak'), pak, f'-Create={response}', '-compress'], output / 'pak.log')
    run([tool(engine, 'UnrealPak'), pak, '-Test'], output / 'pak-test.log')
    run([tool(engine, 'UnrealPak'), pak, '-List'], output / 'pak-list.log')
    digest = file_hash(pak)
    (output / f'{pak.name}.sha256').write_text(f'{digest}  {pak.name}\n', encoding='utf-8')
    manifest = {
        'schema_version': 1,
        'prepared_inputs': state,
        'engine_path': str(Path(engine).resolve()),
        'engine': engine_info,
        'cook': cook_receipt,
        'tool_hashes': {name: file_hash(tool(engine, name)) if tool(engine, name).is_file() else None
                        for name in ('UE4Editor-Cmd', 'UnrealPak')},
        'target': 'WindowsNoEditor',
        'pak_sha256': digest,
        'files': files,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=ROOT / 'build-lock.json')
    parser.add_argument('--mod-config', type=Path, help='Mod source and package descriptor JSON')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('validate-lock')
    commands.add_parser('validate-mod')
    prep = commands.add_parser('prepare')
    prep.add_argument('--workspace', required=True, type=Path)
    prep.add_argument('--sdk-template', type=Path, default=os.environ.get('ARGON_SDK_ROOT'),
                      help='Copy an image SDK into the job workspace instead of downloading it')
    prep.add_argument('--mod-source', type=Path, help='Read-only local mod checkout/content mount')
    prep.add_argument('--image-reference', default=os.environ.get('BUILDER_IMAGE_REFERENCE'),
                      help='Caller-supplied image reference pinned by digest (not runtime attested)')
    for name in ('build-editor', 'cook', 'package'):
        sub = commands.add_parser(name)
        sub.add_argument('--engine', required=True, type=Path)
        sub.add_argument('--sdk', required=True, type=Path)
        if name == 'package':
            sub.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    lock = lockfile(args.lock)
    mod = mod_config(args.mod_config) if args.mod_config else None
    if args.command in ('cook', 'package', 'validate-mod') and mod is None:
        parser.error('--mod-config is required for this command')
    if args.command == 'prepare':
        prepare(lock, args.workspace, mod, args.sdk_template, args.mod_source, args.image_reference)
    elif args.command == 'build-editor':
        build_editor(args.engine, args.sdk, lock)
    elif args.command == 'cook':
        cook(args.engine, args.sdk, mod)
    elif args.command == 'package':
        package(args.engine, args.sdk, args.output, lock, mod)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)
