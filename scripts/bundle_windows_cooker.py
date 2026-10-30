#!/usr/bin/env python3
"""Seal a workload-free Windows cooker for a local Wine experiment."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import zipfile

import builder
import workspace


def selected_files(root):
    root = Path(root)
    result = []
    for path in workspace.checked_tree(root, ignore_git=True):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        # No runtime job state or compilation intermediates; keep shader source,
        # content, plugin descriptors and all built runtime libraries.
        if any(part in {'Saved', 'Intermediate', 'DerivedDataCache'} for part in relative.parts[:-1]):
            continue
        result.append(path)
    return result


def seal(archive, output, age, recipient):
    if not re.fullmatch(r'age1[0-9a-z]{58}', recipient):
        raise ValueError('An X25519 age recipient is required')
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if archive.is_relative_to(output):
        raise ValueError('Plaintext archive must stay outside the upload directory')
    output.mkdir(parents=True, exist_ok=False)
    encrypted = output / 'windows-cooker.zip.age'
    subprocess.run([str(age), '--encrypt', '--recipient', recipient,
                    '--output', str(encrypted), str(archive)], check=True)
    report = {'schema_version': 1, 'encryption': 'age-X25519',
              'recipient': recipient, 'ciphertext_sha256': workspace.file_hash(encrypted),
              'ciphertext_bytes': encrypted.stat().st_size,
              'archive_sha256': workspace.file_hash(archive),
              'archive_bytes': archive.stat().st_size,
              'purpose': 'local_wine_probe_not_registry_publication'}
    workspace.write_json(output / 'transfer.json', report)
    return report


def bundle(engine, sdk, archive, lock):
    engine, sdk, archive = Path(engine).resolve(), Path(sdk).resolve(), Path(archive).resolve()
    if any(archive.is_relative_to(root) for root in (engine, sdk)):
        raise ValueError('Archive must be outside both input trees')
    engine_info = workspace.engine_identity(engine, lock['engine'], 'Win64')
    sdk_info = workspace.verified_sdk(sdk, lock['argon_sdk']['commit'])
    state = workspace.verify_inputs(sdk, None, lock)
    if state['inputs']:
        raise ValueError('Only a workload-free SDK may be transferred')
    if not (sdk / 'Binaries/Win64/UE4Editor-TBL.dll').is_file():
        raise ValueError('Precompiled Windows SDK modules are required')
    manifest = {'schema_version': 1, 'engine': engine_info, 'sdk': sdk_info, 'files': []}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True, strict_timestamps=False) as stream:
        for prefix, root in [('engine', engine), ('sdk', sdk)]:
            for path in selected_files(root):
                name = prefix + '/' + path.relative_to(root).as_posix()
                stream.write(path, name)
                manifest['files'].append({'path': name, 'sha256': workspace.file_hash(path),
                                          'size': path.stat().st_size})
        stream.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'sdk', 'archive', 'output', 'age'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--recipient', required=True)
    args = parser.parse_args()
    # Validate recipient before spending time archiving licensed trees.
    if not re.fullmatch(r'age1[0-9a-z]{58}', args.recipient):
        raise ValueError('An X25519 age recipient is required')
    lock = builder.lockfile(builder.ROOT / 'build-lock.json')
    bundle(args.engine, args.sdk, args.archive, lock)
    print(json.dumps(seal(args.archive, args.output, args.age, args.recipient)), flush=True)


if __name__ == '__main__':
    main()
