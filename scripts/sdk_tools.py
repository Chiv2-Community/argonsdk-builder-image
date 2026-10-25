"""Explicit, verified SDK build-rule patches; never remove reflected classes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

RECEIPT = '.builder-sdk-patches.json'
BUILD_RULES = 'Source/TBL/TBL.Build.cs'


def add_rhi(before):
    needle = b'            "Engine",'
    if before.count(needle) != 1 or b'"RHI"' in before:
        raise ValueError('Unexpected SDK build rules for the Linux RHI dependency patch')
    newline = b'\r\n' if b'\r\n' in before else b'\n'
    return before.replace(needle, needle + newline + b'            "RHI",')


def patch_identity(root, commit):
    before = subprocess.check_output(['git', '-C', str(root), 'show', f'{commit}:{BUILD_RULES}'])
    after = add_rhi(before)
    receipt = {'schema_version': 1, 'source_commit': commit, 'patch': 'linux-tbl-rhi-dependency-v1',
               'path': BUILD_RULES, 'before_sha256': hashlib.sha256(before).hexdigest(),
               'after_sha256': hashlib.sha256(after).hexdigest()}
    return receipt, after


def verify_patch(root, commit):
    root = Path(root)
    expected, after = patch_identity(root, commit)
    receipt = json.loads((root / RECEIPT).read_text(encoding='utf-8'))
    if receipt != expected or (root / BUILD_RULES).read_bytes() != after:
        raise ValueError('SDK build-rule patch does not match its pinned baseline and approved transformation')
    return receipt


def apply_linux_rhi(root, commit):
    # Import here to keep patch verification usable from workspace without a cycle.
    import workspace
    root = Path(root)
    identity = workspace.verified_sdk(root, commit)
    if 'build_rule_patch' in identity:
        return identity
    receipt, after = patch_identity(root, commit)
    (root / BUILD_RULES).write_bytes(after)
    workspace.write_json(root / RECEIPT, receipt)
    identity = workspace.verified_sdk(root, commit)
    workspace.write_json(root / workspace.SDK_IDENTITY, identity)
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['apply-linux-rhi'])
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding='utf-8'))
    print(json.dumps(apply_linux_rhi(args.sdk, lock['argon_sdk']['commit']), indent=2))


if __name__ == '__main__':
    main()
