#!/usr/bin/env python3
"""Local archive round-trip probe. Never upload its licensed bundle or inventory."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time
import zipfile

import workspace


PRODUCT_SUFFIXES = {'.exe', '.dll', '.lib', '.obj', '.pch'}


def inventory(root):
    return [dict(path=path.relative_to(root).as_posix(),
                 sha256=workspace.file_hash(path), size=path.stat().st_size,
                 mtime_ns=path.stat().st_mtime_ns)
            for path in workspace.checked_tree(root) if path.is_file()]


def roundtrip(engine, storage, reserve=5 * 1024**3):
    engine, storage = Path(engine).resolve(), Path(storage).resolve()
    if storage.is_relative_to(engine) or engine.is_relative_to(storage):
        raise ValueError('Bundle storage and engine must be separate trees')
    if (engine / '.git').exists():
        raise ValueError('Move Git metadata outside the engine before bundling')
    if not (engine / '.builder-engine.json').is_file():
        raise ValueError('A validated built engine receipt is required')
    storage.mkdir(parents=True, exist_ok=False)
    files = inventory(engine)
    directories = [p.relative_to(engine).as_posix() for p in workspace.checked_tree(engine) if p.is_dir()]
    size = sum(row['size'] for row in files)
    # Keep both the original tree and archive on the storage drive. Never delete
    # a successful build merely to make room for this experiment.
    if shutil.disk_usage(storage).free < size + reserve:
        raise ValueError('Insufficient space for an uncompressed worst-case archive')
    archive = storage / 'engine.zip'
    started = time.monotonic()
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True, strict_timestamps=False) as bundle:
        for row in files:
            bundle.write(engine / row['path'], row['path'])
    pack_seconds = time.monotonic() - started
    archive_hash = workspace.file_hash(archive)
    manifest = {'files': files, 'directories': directories, 'archive_sha256': archive_hash}
    workspace.write_json(storage / 'inventory.json', manifest)
    if shutil.disk_usage(storage).free < size + reserve:
        raise ValueError('Insufficient space to retain the original engine beside its archive')
    # Cross-volume move frees the original engine drive for an independent
    # restoration at the same absolute path expected by generated build state.
    original = storage / 'original-engine'
    shutil.move(str(engine), str(original))
    if engine.exists():
        raise ValueError('Original engine path must be absent before restoration')
    if workspace.file_hash(archive) != archive_hash:
        raise ValueError('Archive hash changed before restoration')
    engine.mkdir()
    started = time.monotonic()
    with zipfile.ZipFile(archive) as bundle:
        if bundle.namelist() != [row['path'] for row in files]:
            raise ValueError('Archive inventory mismatch')
        for row in files:
            # Entries came from the checked local tree, not an external bundle.
            target = engine / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(row['path']) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest)
            os.utime(target, ns=(row['mtime_ns'], row['mtime_ns']))
        for relative in directories:
            (engine / relative).mkdir(parents=True, exist_ok=True)
    restore_seconds = time.monotonic() - started
    if inventory(engine) != files:
        raise ValueError('Restored files, hashes, sizes or timestamps differ')
    report = {'verification': 'engine_archive_roundtrip_passed',
              'files': len(files), 'tree_bytes': size, 'archive_bytes': archive.stat().st_size,
              'archive_sha256': archive_hash, 'pack_seconds': pack_seconds,
              'restore_seconds': restore_seconds,
              'cross_runner_validation': 'not_run', 'persistent_storage': 'not_configured'}
    return report


def verify_products(engine, storage, report_path=None):
    files = json.loads((Path(storage) / 'inventory.json').read_text())['files']
    expected = [row for row in files if Path(row['path']).suffix.lower() in PRODUCT_SUFFIXES]
    if not expected:
        raise ValueError('No engine build products to verify')
    actual = [row for row in inventory(Path(engine)) if Path(row['path']).suffix.lower() in PRODUCT_SUFFIXES]
    before = {row['path']: row for row in expected}
    after = {row['path']: row for row in actual}
    changes = []
    for path in sorted(before.keys() | after.keys()):
        if path not in before:
            changes.append({'path': path, 'change': 'added'})
        elif path not in after:
            changes.append({'path': path, 'change': 'removed'})
        elif before[path] != after[path]:
            fields = [field for field in ('sha256', 'size', 'mtime_ns')
                      if before[path][field] != after[path][field]]
            changes.append({'path': path, 'change': 'modified', 'fields': fields})
    report = {'verification': 'engine_build_products_changed' if changes else 'engine_build_products_unchanged',
              'products': len(expected), 'changes': changes}
    # Preserve failure evidence before raising; do not weaken the acceptance gate.
    if report_path is not None:
        workspace.write_json(report_path, report)
    if changes:
        raise ValueError('Engine build products changed during consumer validation')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['roundtrip', 'verify-products'])
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'roundtrip':
        report = roundtrip(args.engine, args.storage)
    else:
        report = verify_products(args.engine, args.storage, args.report)
    workspace.write_json(args.report, report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
