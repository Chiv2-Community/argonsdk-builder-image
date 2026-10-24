#!/usr/bin/env python3
"""Pinned SDK preparation and Windows content cooking. No publication commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SUFFIXES = {'.uasset', '.umap', '.uexp', '.ubulk'}


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
    for key in ('argon_sdk', 'engine_candidate'):
        if not re.fullmatch('[0-9a-f]{40}', data[key]['commit']):
            raise ValueError(f'Invalid {key} commit')
    return data


def relative_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
        raise ValueError('Content paths must be relative forward-slash paths')
    if any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('Content paths must not contain empty, dot, or parent segments')
    return value


def mod_config(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]*', data['name']):
        raise ValueError('Invalid mod artifact name')
    if not re.fullmatch('[0-9a-f]{40}', data['commit']):
        raise ValueError('Mod commit must be a full SHA')
    if not re.fullmatch(r'https://[^\s]+', data['repository']):
        raise ValueError('Mod repository must be an HTTPS URL')
    data['content_path'] = relative_path(data.get('content_path', 'Content'))
    package = relative_path(data['package_path'])
    if not package.startswith('Mods/') or not re.fullmatch(r'[A-Za-z0-9_/]+', package):
        raise ValueError('Package path must name a mod directory under Mods/')
    return data


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


def prepare(lock, workspace, mod=None):
    workspace = Path(workspace).resolve()
    sdk, source = workspace / 'ArgonSDK', workspace / 'mod-source'
    if sdk.exists() or (mod is not None and source.exists()):
        raise ValueError('Use a fresh workspace; existing source directories are never replaced')
    checkout(lock['argon_sdk']['repository'], lock['argon_sdk']['commit'], sdk)
    if mod is None:
        return
    checkout(mod['repository'], mod['commit'], source)
    content = (source / mod['content_path']).resolve()
    if not content.is_relative_to(source) or not content.is_dir():
        raise ValueError('Mod content must be a directory inside its checkout')
    target = sdk / 'Content' / mod['package_path']
    if not target.resolve().is_relative_to((sdk / 'Content').resolve()):
        raise ValueError('Mod destination escapes SDK content')
    if target.exists():
        raise ValueError(f'Refusing to replace SDK content: {target}')
    shutil.copytree(content, target)


def tool(engine, name):
    engine = Path(engine).resolve()
    if name == 'build':
        return engine / 'Engine/Build/BatchFiles/Build.bat'
    return engine / 'Engine/Binaries/Win64' / f'{name}.exe'


def build_editor(engine, sdk):
    if os.name != 'nt':
        raise ValueError('Windows editor baseline requires a Windows host')
    run([tool(engine, 'build'), 'TBLEditor', 'Win64', 'Development',
         f'-Project={Path(sdk).resolve() / "TBL.uproject"}', '-WaitMutex', '-NoHotReload'])


def cook(engine, sdk, mod):
    if os.name != 'nt':
        raise ValueError('Windows cooking is not implemented on native Linux')
    sdk = Path(sdk).resolve()
    cooked = sdk / 'Saved/Cooked/WindowsNoEditor'
    if cooked.exists():
        raise ValueError(f'Clean cook required; use a fresh SDK checkout: {cooked}')
    run([tool(engine, 'UE4Editor-Cmd'), sdk / 'TBL.uproject', '-run=Cook',
         '-TargetPlatform=WindowsNoEditor', f'-CookDir={sdk / "Content" / mod["package_path"]}',
         '-unattended', '-nop4', '-UTF8Output', '-NullRHI',
         '-ini:Game:[/Script/UnrealEd.ProjectPackagingSettings]:BlueprintNativizationMethod=Disabled'])


def inventory(root):
    root = Path(root).resolve()
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink not allowed in package input: {path}')
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
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(engine, sdk, output, lock, mod):
    if os.name != 'nt':
        raise ValueError('Packaging baseline requires Windows UnrealPak')
    sdk, output = Path(sdk).resolve(), Path(output).resolve()
    source = sdk / 'Content' / mod['package_path']
    entries = inventory(sdk / 'Saved/Cooked/WindowsNoEditor/TBL/Content' / mod['package_path'])
    source_packages = {p.relative_to(source).as_posix() for p in source.rglob('*')
                       if p.suffix in {'.uasset', '.umap'}}
    cooked_packages = {rel for _, rel in entries if Path(rel).suffix in {'.uasset', '.umap'}}
    if not source_packages or source_packages != cooked_packages:
        raise ValueError('Source/cooked package inventory mismatch; refusing incomplete PAK')
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
        'inputs': lock,
        'mod': mod,
        'engine_path': str(Path(engine).resolve()),
        'engine_build_version': json.loads((Path(engine) / 'Engine/Build/Build.version').read_text(encoding='utf-8')),
        'target': 'WindowsNoEditor',
        'pak_sha256': digest,
        'files': [{'path': rel, 'sha256': file_hash(path)} for path, rel in entries],
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=ROOT / 'build-lock.json')
    parser.add_argument('--mod-config', type=Path, help='Mod source and package descriptor JSON')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('validate-lock')
    prep = commands.add_parser('prepare')
    prep.add_argument('--workspace', required=True, type=Path)
    for name in ('build-editor', 'cook', 'package'):
        sub = commands.add_parser(name)
        sub.add_argument('--engine', required=True, type=Path)
        sub.add_argument('--sdk', required=True, type=Path)
        if name == 'package':
            sub.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    lock = lockfile(args.lock)
    mod = mod_config(args.mod_config) if args.mod_config else None
    if args.command in ('cook', 'package') and mod is None:
        parser.error('--mod-config is required for cook and package')
    if args.command == 'prepare':
        prepare(lock, args.workspace, mod)
    elif args.command == 'build-editor':
        build_editor(args.engine, args.sdk)
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
