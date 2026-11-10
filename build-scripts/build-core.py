#!/usr/bin/env python3
"""Build untouched upstream cgo sources with a frozen dependency graph."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / 'Core/upstream.lock.json').read_text())
SOURCE = ROOT / 'Vendor/libXray'
parser = argparse.ArgumentParser()
parser.add_argument('--go', required=True, type=Path, help='Path to the pinned Go executable')
parser.add_argument('--test-server', action='store_true', help='Also build the isolated Xray test server')
parser.add_argument('--mac-only', action='store_true', help='Build native arm64 smoke-test archive only')
args = parser.parse_args()
go = args.go.resolve()
version = subprocess.check_output([go, 'version'], text=True)
if f"go{LOCK['go']} " not in version:
    raise SystemExit('Go version differs from upstream.lock.json')
os.environ.update(PATH=str(go.parent) + os.pathsep + os.environ['PATH'], GOTOOLCHAIN='local', GOWORK='off', PYTHONDONTWRITEBYTECODE='1')
cache = ROOT / '.cache/core'
os.environ.setdefault('GOMODCACHE', str(cache / 'modules'))
os.environ.setdefault('GOCACHE', str(cache / 'build'))
sys.dont_write_bytecode = True
subprocess.run([sys.executable, ROOT / 'scripts/verify-upstream.py'], check=True)
sys.path.insert(0, str(SOURCE / 'build'))
from app.apple_go import AppleGoBuilder

def check_manifests():
    for name, digest in LOCK['manifest_sha256'].items():
        if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f'{name} differs from audited upstream')

def check_graph():
    graph = subprocess.check_output([go, 'list', '-mod=readonly', '-m', 'all'], cwd=SOURCE, text=True)
    if graph != (ROOT / 'Core/modules.lock.txt').read_text():
        raise SystemExit('Dependency graph differs from Core/modules.lock.txt')
    if any('=>' in line for line in graph.splitlines()):
        raise SystemExit('Unexpected module replacement')
    if f"github.com/xtls/xray-core {LOCK['xray_core']['module_version']}" not in graph.splitlines():
        raise SystemExit('Unexpected Xray-core in dependency graph')
    return graph

class FrozenAppleBuilder(AppleGoBuilder):
    # Reuse upstream target definitions, compiler flags, C bridge and packaging.
    # Deliberately exclude its mutable go-get/tidy and optional geo downloads.
    def init_go_env(self):
        check_manifests()
        subprocess.run([go, 'mod', 'download'], cwd=SOURCE, check=True)
        subprocess.run([go, 'mod', 'verify'], cwd=SOURCE, check=True)
        check_manifests()
        check_graph()

    def download_geo(self):
        pass  # E1 configurations do not use geoip/geosite assets.

check_manifests()
out = ROOT / 'Artifacts'
out.mkdir(exist_ok=True)
builder = FrozenAppleBuilder(str(SOURCE / 'build'))
if args.mac_only:
    builder.before_build()
    builder.build_targets([t for t in builder.macos_targets if t.go_arch == 'arm64'])
    destination = out / 'NativeSmoke'
    destination.mkdir(exist_ok=True)
    for name in ('libXray.a', 'libXray.h'):
        shutil.copy2(Path(builder.framework_dir) / 'macosx-arm64' / name, destination / name)
    shutil.copy2(SOURCE / 'build/template/module.modulemap', destination / 'module.modulemap')
else:
    builder.build()
    check_manifests()
    destination = out / 'LibXray.xcframework'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(SOURCE / 'LibXray.xcframework', destination)
check_manifests()
graph = check_graph()
(out / 'core-modules.txt').write_text(graph)
provenance = {
    'go': version.strip(), 'libxray_commit': LOCK['libxray']['commit'],
    'xcode': subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
    'modules_sha256': hashlib.sha256(graph.encode()).hexdigest(),
    'local_core_patches': [], 'geo_assets': [],
    'files': {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob('*')) if p.is_file()},
}
(out / (destination.name + '.provenance.json')).write_text(json.dumps(provenance, indent=2) + '\n')
print(f'Built and recorded: {destination}', flush=True)

if args.test_server:
    server = out / 'TestServer/xray'
    server.parent.mkdir(exist_ok=True)
    subprocess.run([go, 'build', '-mod=readonly', '-trimpath', '-o', str(server), 'github.com/xtls/xray-core/main'], cwd=SOURCE, check=True)
    check_manifests()
    print(f'Local test server: {server}')
