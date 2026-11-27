#!/usr/bin/env python3
"""Inspect architecture, Mach-O platform and C ABI of every XCFramework slice."""
from pathlib import Path
import hashlib
import json
import plistlib
import re
import subprocess
import argparse

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--probe', action='store_true', help='Verify app-only probe artifact and overlay provenance')
args = parser.parse_args()
name = 'ProbeCore.xcframework' if args.probe else 'LibXray.xcframework'
framework = root / 'Artifacts' / name
info = plistlib.loads((framework / 'Info.plist').read_bytes())
expected = {('ios', ''): ({'arm64'}, 2, 15), ('ios', 'simulator'): ({'arm64', 'x86_64'}, 7, 15),
            ('macos', ''): ({'arm64', 'x86_64'}, 1, 15), ('tvos', ''): ({'arm64'}, 3, 18),
            ('tvos', 'simulator'): ({'arm64', 'x86_64'}, 8, 18)}
assert len(info['AvailableLibraries']) == 5
for lib in info['AvailableLibraries']:
    key = (lib['SupportedPlatform'], lib.get('SupportedPlatformVariant', ''))
    arches, platform, minimum = expected.pop(key)
    assert set(lib['SupportedArchitectures']) == arches
    binary = framework / lib['LibraryIdentifier'] / lib['LibraryPath']
    if binary.suffix == '.framework': binary = binary / 'ProbeCore'
    assert set(subprocess.check_output(['lipo', '-archs', binary], text=True).split()) == arches
    loads = subprocess.check_output(['xcrun', 'otool', '-l', binary], text=True)
    assert {int(p) for p in re.findall(r'^\s*platform (\d+)$', loads, re.M)} == {platform}, key
    versions = re.findall(r'^\s*minos (\d+(?:\.\d+){0,2})$', loads, re.M)
    assert versions and all(tuple(map(int, v.split('.'))) <= (minimum, 0, 0) for v in versions), key
    for arch in sorted(arches):
        symbols = subprocess.check_output(['xcrun', 'nm', '-arch', arch, '-gU', binary], text=True, stderr=subprocess.DEVNULL)
        required = ['_CGoInvoke', '_CGoFree']
        if args.probe:
            required += ['_CGoNewProbeRequest', '_CGoCancelProbeRequest', '_CGoRunProbeRequest', '_CGoFreeProbeRequest']
        for symbol in required:
            assert len(re.findall(r'\bT ' + symbol + r'$', symbols, re.M)) == 1, (key, arch, symbol)
    print(f'{key}: architectures, platform, minimum OS and C ABI passed.')
assert not expected
provenance = json.loads((root / 'Artifacts' / (name + '.provenance.json')).read_text())
lock = json.loads((root / 'Core/upstream.lock.json').read_text())
assert provenance['go'].split()[2] == 'go' + lock['go'], 'Framework toolchain differs from the pinned Go version'
if not args.probe:
    assert provenance['libxray_commit'] == lock['libxray']['commit'], 'Tunnel framework differs from pinned libXray'
    assert provenance['modules_sha256'] == hashlib.sha256((root / 'Core/modules.lock.txt').read_bytes()).hexdigest()
for name, digest in provenance['files'].items():
    assert hashlib.sha256((framework / name).read_bytes()).hexdigest() == digest, name
print('Binary hashes match build provenance.')

if args.probe:
    module = root / 'Core/ProbeCore'
    assert json.loads((module / 'upstream-files.json').read_text()) == provenance['upstreamFiles']
    assert set(provenance['adapterSources']) == {p.name for p in module.glob('*.go') if not p.name.endswith('_test.go')}
    for name, digest in {'isolation.patch': provenance['isolationPatchSHA256'], 'main.go': provenance['adapterSHA256'], **provenance['moduleFiles'], **provenance['adapterSources']}.items():
        assert hashlib.sha256((module / name).read_bytes()).hexdigest() == digest, name
    lock = json.loads((root / 'Core/upstream.lock.json').read_text())
    assert provenance['libxrayCommit'] == lock['libxray']['commit']
    assert provenance['xrayModule'] == lock['xray_core']['module_version']
    print('App-only adapter and isolation overlay match build provenance.')
    native = root / 'Artifacts/ProbeNativeSmoke'
    native_provenance = json.loads((root / 'Artifacts/ProbeNativeSmoke.provenance.json').read_text())
    for key in ['go', 'libxrayCommit', 'xrayModule', 'isolationPatchSHA256', 'upstreamFiles', 'adapterSHA256', 'adapterSources', 'moduleFiles']:
        assert native_provenance[key] == provenance[key], 'Native probe provenance differs: ' + key
    for name, digest in native_provenance['files'].items():
        assert hashlib.sha256((native / name).read_bytes()).hexdigest() == digest, name
    print('Native test archive matches the same adapter and overlay provenance.')
