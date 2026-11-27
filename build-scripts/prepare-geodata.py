#!/usr/bin/env python3
"""Fetch the two checksum-pinned release assets used by the Xray Apple packages."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'Core/geodata.lock.json').read_text())
parser = argparse.ArgumentParser()
parser.add_argument('--download', action='store_true')
parser.add_argument('--directory', type=Path, default=root / 'Artifacts/Geodata')
args = parser.parse_args()
def digest(data): return hashlib.sha256(data).hexdigest()
if args.download:
    args.directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.directory) as temporary:
        stage = Path(temporary)
        for name, expected in lock['files'].items():
            subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                            '--proto', '=https', '--proto-redir', '=https', '--retry', '2', '--max-time', '120',
                            '--max-filesize', str(64 * 1024 * 1024), lock['assets'][name], '-o', stage / name], check=True)
            if digest((stage / name).read_bytes()) != expected: raise SystemExit('Geodata digest mismatch: ' + name)
        for name in lock['files']:
            (stage / name).replace(args.directory / name)
for name, expected in lock['files'].items():
    if digest((args.directory / name).read_bytes()) != expected: raise SystemExit('Geodata differs: ' + name)
print('Pinned geoip/geosite SHA-256 checks passed.')
