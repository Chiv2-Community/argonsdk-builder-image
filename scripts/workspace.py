"""Validated content inputs and private, copy-based SDK workspaces."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
from urllib.parse import urlsplit
import engine_tools

STATE = '.builder-state.json'
SDK_IDENTITY = '.builder-sdk.json'
RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {
    f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)
}


def safe_component(value, spaces=False):
    pattern = '[A-Za-z0-9_][A-Za-z0-9_. -]*' if spaces else '[A-Za-z0-9_][A-Za-z0-9_.-]*'
    if (not isinstance(value, str) or not re.fullmatch(pattern, value)
            or value.endswith(('.', ' ')) or value.split('.')[0].upper() in RESERVED):
        raise ValueError(f'Invalid portable name: {value!r}')
    return value


def relative_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Content paths must be nonempty relative forward-slash paths')
    for part in value.split('/'):
        safe_component(part, spaces=True)
    return value


def descriptor(data, dependencies=True):
    if not isinstance(data, dict):
        raise ValueError('Mod descriptor must be an object')
    allowed = {'schema_version', 'name', 'repository', 'commit', 'content_path', 'package_path'}
    if dependencies:
        allowed.add('dependencies')
    if set(data) - allowed:
        raise ValueError(f'Unknown descriptor fields: {sorted(set(data) - allowed)}')
    data = dict(data)
    # Unversioned scaffold descriptors remain accepted as version 1.
    if type(data.get('schema_version', 1)) is not int or data.get('schema_version', 1) != 1:
        raise ValueError('Only descriptor schema_version 1 is supported')
    data['schema_version'] = 1
    safe_component(data['name'])
    if not isinstance(data['commit'], str) or not re.fullmatch('[0-9a-f]{40}', data['commit']):
        raise ValueError('Mod commit must be a full SHA')
    url = urlsplit(data['repository'])
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(c.isspace() for c in data['repository'])):
        raise ValueError('Repository must be an HTTPS URL without credentials, query, or fragment')
    data['content_path'] = relative_path(data.get('content_path', 'Content'))
    package = relative_path(data['package_path'])
    if not package.startswith('Mods/') or not re.fullmatch('[A-Za-z0-9_/]+', package):
        raise ValueError('Package path must name a mod directory under Mods/')
    if dependencies:
        deps = data.get('dependencies', [])
        if not isinstance(deps, list):
            raise ValueError('dependencies must be an array')
        data['dependencies'] = [descriptor(dep, dependencies=False) for dep in deps]
        paths = [entry['package_path'].casefold() for entry in [data, *data['dependencies']]]
        for i, path in enumerate(paths):
            if any(path == other or path.startswith(other + '/') or other.startswith(path + '/')
                   for other in paths[i + 1:]):
                raise ValueError('Mod and dependency package paths must not overlap')
    return data


def is_link(path):
    flags = getattr(path.lstat(), 'st_file_attributes', 0)
    return path.is_symlink() or bool(flags & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def checked_tree(root, ignore_git=False):
    """Reject links, special files, and case collisions before copying or hashing."""
    root = Path(root)
    if not root.is_dir() or is_link(root):
        raise ValueError(f'Input must be a real directory: {root}')
    seen = set()
    result = []
    pending = [root]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            rel = path.relative_to(root)
            if ignore_git and path.name == '.git':
                continue
            # Check before descending, including Windows junctions.
            if is_link(path):
                raise ValueError(f'Links and reparse points are not allowed: {path}')
            if not path.is_file() and not path.is_dir():
                raise ValueError(f'Special files are not allowed: {path}')
            if rel.as_posix().casefold() in seen:
                raise ValueError(f'Case-insensitive path collision: {rel}')
            seen.add(rel.as_posix().casefold())
            if (re.search(r'[<>:"\\|?*\x00-\x1f]', path.name)
                    or path.name.endswith(('.', ' ')) or path.name.split('.')[0].upper() in RESERVED):
                raise ValueError(f'Nonportable file name: {rel}')
            result.append(path)
            if path.is_dir():
                pending.append(path)
    return sorted(result)


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(root):
    root = Path(root)
    return [{'path': path.relative_to(root).as_posix(), 'sha256': file_hash(path)}
            for path in checked_tree(root) if path.is_file()]


def directory_within(root, relative):
    root = Path(root).absolute()
    path = root
    for part in [None, *relative.split('/')]:
        if part is not None:
            if path.is_dir() and any(child.name.casefold() == part.casefold() and child.name != part
                                     for child in path.iterdir()):
                raise ValueError(f'Case-insensitive path collision under {path}: {part}')
            path = path / part
        if (path.exists() or path.is_symlink()) and is_link(path):
            raise ValueError(f'Links and reparse points are not allowed: {path}')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Content directory escapes its root')
    return path


def git_identity(root):
    root = Path(root)
    # Do not accidentally report an enclosing repository as the source identity.
    if not (root / '.git').exists():
        return None
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).rstrip('\r\n')
    status = git('status', '--porcelain', '--untracked-files=all', '--', '.',
                 f':(exclude){SDK_IDENTITY}', f':(exclude){STATE}')
    submodules = git('submodule', 'status', '--recursive')
    return {'commit': git('rev-parse', 'HEAD'), 'dirty': bool(status),
            'submodules': submodules.splitlines() if submodules else []}


def verified_sdk(root, expected):
    identity = git_identity(root)
    if identity is None:
        raise ValueError('SDK template must retain Git metadata for revision verification')
    if identity['commit'] != expected or identity['dirty']:
        raise ValueError('SDK checkout does not match the clean pinned SDK revision')
    # A leading space denotes an initialized submodule at its recorded commit.
    for line in identity['submodules']:
        if not line.startswith(' '):
            raise ValueError('SDK submodules must be initialized at their recorded commits')
    return identity


def engine_identity(root, pin, platform=None):
    return engine_tools.identity(root, pin, platform)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def prepare(lock, directory, mod, checkout, template=None, local_source=None, image_reference=None):
    directory = Path(directory).absolute()
    sdk = directory / 'ArgonSDK'
    roots = [Path(value).resolve() for value in (template, local_source) if value is not None]
    if any(directory.resolve().is_relative_to(root) or root.is_relative_to(directory.resolve())
           for root in roots):
        raise ValueError('Workspace must not overlap the SDK template or mounted mod source')
    if local_source is not None and mod is None:
        raise ValueError('A mounted mod source requires --mod-config')
    if image_reference is not None and not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image_reference):
        raise ValueError('Image reference must include an immutable SHA-256 digest')
    directory.mkdir(parents=True, exist_ok=True)
    if sdk.exists() or (directory / 'sources').exists():
        raise ValueError('Use a fresh workspace; existing directories are never replaced')
    # Atomic reservation prevents two jobs from claiming one workspace.
    with (directory / '.builder-reserved').open('x', encoding='utf-8') as marker:
        marker.write('Use a new workspace after either success or failure.\n')
    if template is None:
        checkout(lock['argon_sdk']['repository'], lock['argon_sdk']['commit'], sdk)
        sdk_identity = verified_sdk(sdk, lock['argon_sdk']['commit'])
    else:
        template = Path(template).resolve()
        sdk_identity = verified_sdk(template, lock['argon_sdk']['commit'])
        checked_tree(template, ignore_git=True)
        # Never hardlink mutable files to the shared template. Omit prior cook/cache state.
        def ignore(path, names):
            ignored = {'.git', SDK_IDENTITY, STATE}
            if Path(path) == template:
                ignored.update({'Saved', 'Intermediate', 'DerivedDataCache'})
            return set(names) & ignored
        shutil.copytree(template, sdk, ignore=ignore)
    write_json(sdk / SDK_IDENTITY, sdk_identity)
    receipts = []
    for index, entry in enumerate([mod, *mod.get('dependencies', [])] if mod else []):
        source = Path(local_source).resolve() if index == 0 and local_source else directory / 'sources' / str(index)
        if not (index == 0 and local_source):
            checkout(entry['repository'], entry['commit'], source)
        identity = git_identity(source)
        if identity is not None and (identity['commit'] != entry['commit'] or identity['dirty']):
            raise ValueError(f'Source does not match clean pinned commit: {entry["name"]}')
        if identity is not None and any(not line.startswith(' ') for line in identity['submodules']):
            raise ValueError('Source submodules must be initialized at recorded commits')
        # Validate the entire mount/checkout before following any content path.
        checked_tree(source, ignore_git=True)
        content = directory_within(source, entry['content_path'])
        files = snapshot(content)
        if not files:
            raise ValueError(f'Empty content input: {entry["name"]}')
        target = directory_within(sdk, 'Content/' + entry['package_path'])
        if not target.resolve().is_relative_to((sdk / 'Content').resolve()) or target.exists():
            raise ValueError(f'Mod destination escapes or replaces SDK content: {target}')
        shutil.copytree(content, target)
        if snapshot(target) != files:
            raise ValueError('Content changed during input copy')
        receipts.append({'descriptor': entry, 'git': identity,
                         'verification': 'git_commit_and_clean_tree' if identity else 'local_content_hashes_only',
                         'files': files})
    state = {'schema_version': 1, 'lock': lock, 'mod': mod, 'sdk': sdk_identity,
             'image': {'reference': image_reference, 'verification': 'caller_supplied_not_runtime_attested'},
             'inputs': receipts}
    write_json(sdk / STATE, state)
    return state


def verify_inputs(sdk, mod, lock=None):
    sdk = Path(sdk).resolve()
    state = json.loads((sdk / STATE).read_text(encoding='utf-8'))
    if state['mod'] != mod or (lock is not None and state['lock'] != lock):
        raise ValueError('Descriptor/lock differs from the prepared workspace')
    for receipt in state['inputs']:
        content = directory_within(sdk, 'Content/' + receipt['descriptor']['package_path'])
        if snapshot(content) != receipt['files']:
            raise ValueError(f'Prepared content changed: {receipt["descriptor"]["name"]}')
    return state
