"""Synthetic tool trees for engine identity tests; these are not real UE builds."""
import json
from pathlib import Path
import engine_tools


def engine_fixture(root, pin, platform='Win64'):
    root = Path(root)
    for rel in engine_tools.tool_files(platform):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f'synthetic fixture: {rel}'.encode())
    (root / 'Engine/Build/Build.version').write_text(json.dumps({
        'MajorVersion': 4, 'MinorVersion': 25, 'PatchVersion': 0,
        'BranchName': engine_tools.BRANCH,
    }))
    archive = root / 'synthetic-source.tar'
    archive.write_bytes(b'synthetic source archive, not an Unreal engine')
    engine_tools.write_receipt(root, pin, platform, archive)
    return root
