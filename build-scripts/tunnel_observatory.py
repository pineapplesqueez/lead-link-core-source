"""Apply only the two audited Observatory changes shared with ProbeCore."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def apply_observatory_patch(xray: Path, root: Path) -> None:
    module = root / 'Core/ProbeCore'
    original = json.loads((module / 'upstream-files.json').read_text())
    patched = json.loads((root / 'Core/upstream.lock.json').read_text())['local_patches']
    if set(patched) != {'app/observatory/observer.go', 'app/observatory/explainErrors.go'}:
        raise ValueError('Unexpected tunnel patch file set')
    for name in patched:
        if hashlib.sha256((xray / name).read_bytes()).hexdigest() != original[name]:
            raise ValueError(f'Unexpected upstream source: {name}')
    folder = xray / 'app/observatory'
    folder.chmod(folder.stat().st_mode | 0o700)
    subprocess.run(['git', 'apply', '--no-index', '--unidiff-zero',
                    *['--include=' + name for name in patched], module / 'isolation.patch'],
                   cwd=xray, env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(xray.parent)}, check=True)
    for name, digest in patched.items():
        if hashlib.sha256((xray / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Unexpected patched source: {name}')
