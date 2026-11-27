#!/usr/bin/env python3
"""Collect notices from actual original/probe dependency graphs on Apple."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def notice_files(module_root, package_dirs):
    """Include notices along imported package paths, never unrelated test trees."""
    module_root = Path(module_root).resolve()
    directories = {module_root}
    for package_dir in package_dirs:
        directory = Path(package_dir).resolve()
        if not directory.is_relative_to(module_root):
            raise ValueError(f'Package outside module: {directory}')
        while directory != module_root:
            directories.add(directory)
            directory = directory.parent
    return sorted({p for directory in directories for p in directory.iterdir()
                   if p.is_file() and p.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE'))},
                  key=lambda p: p.relative_to(module_root).as_posix())


def collect(root, go):
    lock = json.loads((root / 'Core/upstream.lock.json').read_text())
    env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off')
    env.setdefault('GOMODCACHE', str(root / '.cache/core/modules'))
    env.setdefault('GOCACHE', str(root / '.cache/core/build'))
    if f"go{lock['go']} " not in subprocess.check_output([go, 'version'], env=env, text=True):
        raise SystemExit('Go version differs from upstream.lock.json')
    goroot = Path(subprocess.check_output([go, 'env', 'GOROOT'], env=env, text=True).strip()).resolve()
    modules = {}

    def add(name, version, directory, package):
        item = modules.setdefault(name, {'version': version, 'roots': {}})
        item['roots'].setdefault(Path(directory).resolve(), set()).add(Path(package).resolve())

    # tvOS uses these Go targets too; include device and Mac/simulator architectures.
    for source, target in [(root / 'Vendor/libXray', './cgo_bridge'), (root / 'Core/ProbeCore', '.')]:
        for platform, arch in [('darwin', 'arm64'), ('darwin', 'amd64'), ('ios', 'arm64'), ('ios', 'amd64')]:
            output = subprocess.check_output([go, 'list', '-mod=readonly', '-deps', '-json', target],
                                            cwd=source, env=dict(env, GOOS=platform, GOARCH=arch, CGO_ENABLED='1'), text=True)
            decoder = json.JSONDecoder()
            while output.strip():
                output = output.lstrip()
                package, end = decoder.raw_decode(output)
                output = output[end:]
                module = package.get('Module')
                if module:
                    # Own wrapper: modified Xray files remain a separate MPL component.
                    if module.get('Main') and source == root / 'Core/ProbeCore':
                        continue
                    directory = module.get('Replace', {}).get('Dir') or module['Dir']
                    add(module['Path'], module.get('Version', 'pinned source'), directory, package['Dir'])
                elif package.get('Standard') and package.get('Dir'):
                    add('Go standard library and runtime', lock['go'], goroot, package['Dir'])

    sections = [f'Lead Link — third-party notices\n\nThe VPN extension includes unmodified libXray and Xray-core. The app probe core includes a Lead Link isolation overlay; its modified files are distributed under MPL-2.0.\nCorresponding source of the core components (original and modified Xray-core, libXray, ProbeCore, exact versions and build scripts): https://github.com/pineapplesqueez/lead-link-core-source\nXray-core source: https://github.com/XTLS/Xray-core/tree/{lock["xray_core"]["commit_prefix"]}\nlibXray source: https://github.com/XTLS/libXray/tree/{lock["libxray"]["commit"]}\n']
    manifest = []
    for name, module in sorted(modules.items()):
        notices = {}
        for directory, packages in module['roots'].items():
            for path in notice_files(directory, packages):
                relative = path.relative_to(directory).as_posix()
                data = path.read_bytes()
                if relative in notices and notices[relative] != data:
                    raise SystemExit(f'Conflicting notice across core variants: {name}/{relative}')
                notices[relative] = data
        if not notices:
            raise SystemExit(f'Missing notice: {name}')
        sections.append(f'\n{"=" * 72}\n{name} {module["version"]}\n')
        for relative, data in sorted(notices.items()):
            sections.append(f'\n--- {relative} ---\n' + data.decode('utf-8'))
        manifest.append({'module': name, 'version': module['version'],
                         'notices': {path: hashlib.sha256(data).hexdigest() for path, data in sorted(notices.items())}})
    geo = json.loads((root / 'Core/geodata.lock.json').read_text())
    sections.append('\n' + '=' * 72 + '\nBundled Xray geoip/geosite data, Xray-rules-dat ' + geo['release'] + '\nData and source: ' + geo['data_source'] + '\nPinned provenance: Core/geodata.lock.json\n')
    for name, expected in sorted(geo['licenses'].items()):
        file = root / 'Core/GeodataLicenses' / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise SystemExit('Geodata license differs: ' + name)
        sections.append('\n--- ' + name + ' ---\n' + file.read_text())
    return '\n'.join(sections), json.dumps(manifest, indent=2) + '\n', len(modules)


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Check notices/lock without rewriting them')
    args = parser.parse_args()
    notices, manifest, count = collect(root, args.go.resolve())
    for path, content in [(root / 'App/Resources/ThirdPartyNotices.txt', notices), (root / 'Core/licenses.lock.json', manifest)]:
        if args.check:
            if path.read_text() != content:
                raise SystemExit(f'Outdated notices: {path.relative_to(root)}')
        else:
            path.write_text(content)
    print(f'{"Verified" if args.check else "Collected"} notices for {count} components, including imported subpackages; manual release license audit remains required.')


if __name__ == '__main__':
    main()
