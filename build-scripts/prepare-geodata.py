#!/usr/bin/env python3
"""Fetch only pinned data files; verify archive and extracted digests."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'Core/geodata.lock.json').read_text())
parser = argparse.ArgumentParser()
parser.add_argument('--download', action='store_true')
parser.add_argument('--directory', type=Path, default=root / 'Artifacts/Geodata')
args = parser.parse_args()
def digest(data): return hashlib.sha256(data).hexdigest()
if args.download:
    data = urllib.request.urlopen(lock['archive_url'], timeout=60).read(64 * 1024 * 1024)
    if digest(data) != lock['archive_sha256']: raise SystemExit('Xray archive digest mismatch')
    archive = zipfile.ZipFile(io.BytesIO(data))
    files = {name: archive.read(name) for name in lock['files']}
    if any(digest(value) != lock['files'][name] for name, value in files.items()): raise SystemExit('Geodata digest mismatch')
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, value in files.items(): (args.directory / name).write_bytes(value)
for name, expected in lock['files'].items():
    if digest((args.directory / name).read_bytes()) != expected: raise SystemExit('Geodata differs: ' + name)
print('Pinned geoip/geosite SHA-256 checks passed.')
