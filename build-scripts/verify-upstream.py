#!/usr/bin/env python3
"""Compare every upstream source to the checksum-pinned official archive."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'Core/upstream.lock.json').read_text())['libxray']
source = root / 'Vendor/libXray'
cache = root / '.cache/core'
cache.mkdir(parents=True, exist_ok=True)
archive = cache / (lock['commit'] + '.tar.gz')
if not archive.exists():
    subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                    '--proto', '=https', '--proto-redir', '=https', '--max-time', '60',
                    '--max-filesize', str(32 * 1024 * 1024), lock['archive_url'], '-o', str(archive)], check=True)
if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['archive_sha256']:
    raise SystemExit('Upstream archive checksum mismatch')
expected = set()
prefix = 'libXray-' + lock['commit'] + '/'
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        if member.isdir(): continue
        if not member.isfile() or not member.name.startswith(prefix): raise SystemExit('Unexpected archive entry')
        name = member.name[len(prefix):]
        file = (source / name).resolve()
        if not file.is_relative_to(source.resolve()): raise SystemExit('Unsafe archive entry')
        expected.add(name)
        if not file.is_file() or hashlib.sha256(file.read_bytes()).digest() != hashlib.sha256(tar.extractfile(member).read()).digest():
            raise SystemExit('Modified upstream file: ' + name)
for file in source.rglob('*'):
    if file.is_file() and file.suffix in ('.go', '.py') and str(file.relative_to(source)) not in expected:
        raise SystemExit('Unexpected executable upstream source: ' + str(file.relative_to(source)))
print(f'All {len(expected)} upstream files match the official pinned archive; no source patches.')
