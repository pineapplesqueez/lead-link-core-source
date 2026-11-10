#!/usr/bin/env python3
"""Install the checksum-pinned Go toolchain in the project's persistent cache."""
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import tarfile
import tempfile

tool_env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off')
root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'Core/go-toolchain.lock.json').read_text())
if platform.system() != 'Darwin' or platform.machine() != 'arm64' or lock['bootstrap_host'] != 'darwin-arm64':
    raise SystemExit('This bootstrap lock is for Apple Silicon macOS only.')
cache = root / '.cache/toolchains'
cache.mkdir(parents=True, exist_ok=True)
destination = cache / ('go-' + lock['version'])
executable = destination / 'go/bin/go'
receipt = destination / 'receipt.json'
if destination.exists():
    if not receipt.exists() or not executable.exists():
        raise SystemExit('Incomplete existing toolchain; preserve it for inspection before retrying.')
    actual = json.loads(receipt.read_text())
    if actual.get('archive_sha256') != lock['sha256'] or actual.get('executable_sha256') != hashlib.sha256(executable.read_bytes()).hexdigest():
        raise SystemExit('Existing toolchain differs from verified receipt.')
else:
    with tempfile.TemporaryDirectory(prefix='.bootstrap-', dir=cache) as temporary:
        staging = Path(temporary)
        archive = staging / 'go.tar.gz'
        print('Downloading the pinned Go ' + lock['version'] + ' toolchain...', flush=True)
        # System curl uses macOS trust independently of a Python.org CA setup.
        subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                        '--proto', '=https', '--proto-redir', '=https', '--tlsv1.2',
                        '--connect-timeout', '30', '--max-time', '300',
                        '--max-filesize', str(256 * 1024 * 1024), lock['url'], '-o', str(archive)], check=True)
        with archive.open('rb') as downloaded:
            digest = hashlib.file_digest(downloaded, 'sha256').hexdigest()
        if digest != lock['sha256']:
            raise SystemExit('Go archive checksum mismatch; nothing installed.')
        install = staging / 'install'
        install.mkdir()
        with tarfile.open(archive) as package:
            package.extractall(install, filter='data')
        binary = install / 'go/bin/go'
        version = subprocess.check_output([binary, 'version'], env=tool_env, text=True)
        if f"go{lock['version']} " not in version:
            raise SystemExit('Extracted Go version does not match the lock.')
        (install / 'receipt.json').write_text(json.dumps({
            'archive_sha256': lock['sha256'],
            'executable_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'version': version.strip(),
        }, indent=2) + '\n')
        install.rename(destination)
version = subprocess.check_output([executable, 'version'], env=tool_env, text=True).strip()
if f"go{lock['version']} " not in version:
    raise SystemExit('Installed Go version does not match the lock.')
print(version)
print(executable)
