#!/usr/bin/env python3
"""Build pinned libXray with the audited Observatory fix for the tunnel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from tunnel_observatory import apply_observatory_patch

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / 'Core/upstream.lock.json').read_text())
SOURCE = ROOT / 'Vendor/libXray'
parser = argparse.ArgumentParser()
parser.add_argument('--go', required=True, type=Path, help='Path to the pinned Go executable')
parser.add_argument('--test-server', action='store_true', help='Also build the isolated Xray test server')
parser.add_argument('--mac-only', action='store_true', help='Build native arm64 smoke-test archive only')
parser.add_argument('--test-observatory', action='store_true', help='Run regression tests with the Go race detector')
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
        pass  # Already verified before enabling the tunnel workspace.

    def download_geo(self):
        pass  # E1 configurations do not use geoip/geosite assets.

check_manifests()
subprocess.run([go, 'mod', 'download'], cwd=SOURCE, check=True)
subprocess.run([go, 'mod', 'verify'], cwd=SOURCE, check=True)
graph = check_graph()
build_root = ROOT / '.build'
build_root.mkdir(exist_ok=True)
workspace = tempfile.TemporaryDirectory(prefix='tunnel-core-', dir=build_root)
work = Path(workspace.name)
xray_name = 'github.com/xtls/xray-core'
xray_version = LOCK['xray_core']['module_version']
xray = work / 'Xray-core'
shutil.copytree(Path(os.environ['GOMODCACHE']) / (xray_name + '@' + xray_version), xray,
                copy_function=shutil.copyfile)
apply_observatory_patch(xray, ROOT)
subprocess.run([go, 'work', 'init', SOURCE], cwd=work, check=True)
os.environ['GOWORK'] = str(work / 'go.work')
subprocess.run([go, 'work', 'edit', f'-replace={xray_name}@{xray_version}=./Xray-core'], cwd=work, check=True)
resolved = subprocess.check_output([go, 'list', '-m', 'all'], cwd=SOURCE, text=True)
expected = graph.replace(f'{xray_name} {xray_version}\n', f'{xray_name} {xray_version} => ./Xray-core\n')
if resolved != expected:
    raise SystemExit('Unexpected tunnel dependency graph')
if args.test_observatory:
    shutil.copyfile(ROOT / 'Core/Tests/observatory_snapshot_test.go', xray / 'app/observatory/leadlink_test.go')
    subprocess.run([go, 'test', '-race', '-count=3', xray_name + '/app/observatory'], cwd=SOURCE, check=True)
    sys.exit(0)
out = ROOT / 'Artifacts'
out.mkdir(exist_ok=True)
builder = FrozenAppleBuilder(str(SOURCE / 'build'))
if args.mac_only:
    builder.before_build()
    builder.build_targets([t for t in builder.macos_targets if t.go_arch == 'arm64'])
else:
    builder.build()
    check_manifests()
    destination = out / 'LibXray.xcframework'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(SOURCE / 'LibXray.xcframework', destination)
check_manifests()
(out / 'core-modules.txt').write_text(graph)
native = out / 'NativeSmoke'
native.mkdir(exist_ok=True)
for name in ('libXray.a', 'libXray.h'):
    shutil.copy2(Path(builder.framework_dir) / 'macosx-arm64' / name, native / name)
shutil.copy2(SOURCE / 'build/template/module.modulemap', native / 'module.modulemap')
provenance = {
    'go': version.strip(), 'libxray_commit': LOCK['libxray']['commit'],
    'xcode': subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
    'modules_sha256': hashlib.sha256(graph.encode()).hexdigest(),
    'local_core_patches': LOCK['local_patches'], 'geo_assets': [],
}
for artifact in ([native] if args.mac_only else [native, destination]):
    provenance['files'] = {str(p.relative_to(artifact)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(artifact.rglob('*')) if p.is_file()}
    (out / (artifact.name + '.provenance.json')).write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'Built and recorded: {artifact}', flush=True)

if args.test_server:
    os.environ['GOWORK'] = 'off'  # Independent control server uses official Xray.
    server = out / 'TestServer/xray'
    server.parent.mkdir(exist_ok=True)
    subprocess.run([go, 'build', '-mod=readonly', '-trimpath', '-o', str(server), 'github.com/xtls/xray-core/main'], cwd=SOURCE, check=True)
    check_manifests()
    print(f'Local test server: {server}')
