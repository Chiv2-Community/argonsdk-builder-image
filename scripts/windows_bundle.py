"""Verify a trusted-run Windows transfer archive before use under Wine."""
import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

import builder
import workspace


def extract(archive, destination, lock):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Bundle destination must be new')
    with zipfile.ZipFile(archive) as stream:
        if stream.getinfo('manifest.json').file_size > 64 * 1024**2:
            raise ValueError('Bundle manifest is too large')
        manifest = json.loads(stream.read('manifest.json'))
        if (manifest['schema_version'] != 1 or manifest['engine']['commit'] != lock['engine']['commit']
                or manifest['sdk']['commit'] != lock['argon_sdk']['commit'] or manifest['sdk']['dirty']):
            raise ValueError('Bundle source pins do not match the pristine Windows baseline')
        names = [row['path'] for row in manifest['files']]
        if not names or len({name.casefold() for name in names}) != len(names):
            raise ValueError('Bundle file names must be nonempty and unique')
        expected = set(names) | {'manifest.json'}
        if len(stream.namelist()) != len(expected) or set(stream.namelist()) != expected:
            raise ValueError('Archive members differ from the manifest')
        for row in manifest['files']:
            name = row['path']
            path = PurePosixPath(name)
            if (path.is_absolute() or name != path.as_posix() or '..' in path.parts
                    or not path.parts or path.parts[0] not in {'engine', 'sdk'}
                    or any(c in name for c in '\\:\x00\r\n')):
                raise ValueError('Unsafe archive path')
            info = stream.getinfo(name)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.file_size != row['size']:
                raise ValueError('Invalid archive file type or size')
        destination.mkdir(parents=True)
        for row in manifest['files']:
            path = destination / row['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            with stream.open(row['path']) as source, path.open('xb') as target:
                while data := source.read(1024 * 1024):
                    target.write(data)
            if workspace.file_hash(path) != row['sha256']:
                raise ValueError(f'Bundle file hash mismatch: {row["path"]}')
        workspace.write_json(destination / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if workspace.file_hash(args.archive) != args.sha256:
        raise ValueError('Decrypted archive hash mismatch')
    manifest = extract(args.archive, args.destination, builder.lockfile(builder.ROOT / 'build-lock.json'))
    print(json.dumps({'verification': 'bundle_files_verified', 'files': len(manifest['files']),
                      'engine_commit': manifest['engine']['commit'], 'sdk_commit': manifest['sdk']['commit']}))


if __name__ == '__main__':
    main()
