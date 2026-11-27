#!/usr/bin/env python3
"""Fetch only the audited upstream source archive; never execute its scripts."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / 'Core/upstream.lock.json').read_text())


def verify(data, expected, label):
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f'{label}: SHA-256 mismatch; refusing to continue')


def check_source(directory):
    for name, digest in LOCK['manifest_sha256'].items():
        verify((directory / name).read_bytes(), digest, name)
    mod = (directory / 'go.mod').read_text()
    if LOCK['xray_core']['module_version'] not in mod:
        raise SystemExit('Unexpected Xray-core version')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='Keep an old checkout as a backup when installing a new pin')
    args = parser.parse_args()
    destination = ROOT / 'Vendor/libXray'
    if destination.exists():
        if not args.update:
            raise SystemExit('Vendor/libXray already exists; use --update to preserve it and install a different pin.')
        if all((destination / name).is_file() and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
               for name, digest in LOCK['manifest_sha256'].items()):
            return
    # Use the macOS system trust store via curl, independent of Python's CA setup.
    archive = subprocess.check_output([
        '/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
        '--proto', '=https', '--proto-redir', '=https', '--max-time', '60',
        '--max-filesize', str(32 * 1024 * 1024), LOCK['libxray']['archive_url']
    ], timeout=65)
    if len(archive) > 32 * 1024 * 1024:
        raise SystemExit('Archive exceeds size limit')
    verify(archive, LOCK['libxray']['archive_sha256'], 'archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            # Validate paths and forbid links before extraction, including on Python <3.12.
            for member in tar.getmembers():
                target = (stage / member.name).resolve()
                if not target.is_relative_to(stage.resolve()) or not (member.isfile() or member.isdir()):
                    raise SystemExit('Unsafe archive member')
            # Python 3.12+ supplies an additional extraction filter.
            if hasattr(tarfile, 'data_filter'):
                tar.extractall(stage, filter='data')
            else:
                tar.extractall(stage)
        source = stage / ('libXray-' + LOCK['libxray']['commit'])
        check_source(source)
        backup = None
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix='libXray-previous-', dir=destination.parent)) / 'libXray'
            destination.rename(backup)
        try:
            source.rename(destination)
        except OSError:
            if backup is not None:
                backup.rename(destination)
            raise
        if backup is not None:
            print('Previous checkout preserved at', backup)
    print(f'Verified upstream sources: {destination}')
    print('No Go toolchain installed and no core binary built.')


if __name__ == '__main__':
    main()
