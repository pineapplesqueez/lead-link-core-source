#!/usr/bin/env python3
"""Build the app-only, eight-profile adapter; never modify the tunnel artifact."""
import argparse,hashlib,json,os,shutil,subprocess,plistlib
from pathlib import Path
root=Path(__file__).resolve().parent.parent
lock=json.loads((root/'Core/upstream.lock.json').read_text())
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mac-only',action='store_true')
parser.add_argument('--test',action='store_true')
parser.add_argument('--race',action='store_true')
args=parser.parse_args()
go=root/f'.cache/toolchains/go-{lock["go"]}/go/bin/go'
version=subprocess.check_output([str(go),'version'],text=True).strip()
assert f'go{lock["go"]} ' in version
module=root/'Core/ProbeCore';work=root/'.build/probe-core'
cache=(root/'.cache/core/modules').resolve()
env=dict(os.environ,PATH=str(go.parent)+os.pathsep+os.environ['PATH'],GOTOOLCHAIN='local',GOWORK='off',GOMODCACHE=str(cache),GOCACHE=str(work/'go-cache'))
subprocess.run(['python3',str(root/'scripts/verify-upstream.py')],check=True)
subprocess.run([str(go),'mod','download'],cwd=root/'Vendor/libXray',env=env,check=True)
source=cache/f'github.com/xtls/xray-core@{lock["xray_core"]["module_version"]}'
files=json.loads((module/'upstream-files.json').read_text())
for name,digest in files.items():
 assert hashlib.sha256((source/name).read_bytes()).hexdigest()==digest, 'Upstream overlay input changed: '+name
copy=work/'upstream'
if not copy.exists():shutil.copytree(source,copy)
for p in source.rglob('*'):
 if p.is_file():
  q=copy/p.relative_to(source)
  assert q.is_file() and hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256(q.read_bytes()).digest(), 'Generated upstream copy differs'
overlay=work/'overlay'
if overlay.exists():shutil.rmtree(overlay)
for name in files:
 p=overlay/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,p);p.chmod(0o644)
subprocess.run(['patch','--batch','-p1','-i',str(module/'isolation.patch')],cwd=overlay,check=True,stdout=subprocess.DEVNULL)
manifest=work/'overlay.json';manifest.write_text(json.dumps({'Replace':{str(copy/n):str(overlay/n) for n in files}}))
subprocess.run([str(go),'mod','verify'],cwd=module,env=env,check=True,stdout=subprocess.DEVNULL)
graph=subprocess.check_output([str(go),'list','-mod=readonly','-m','-f','{{.Path}} {{.Version}}','all'],cwd=module,env=env,text=True)
modules={line.strip() for line in graph.splitlines() if not line.startswith('leadlink.local/probecore')}
modules.discard('github.com/xtls/libxray v0.0.0');modules.add('github.com/xtls/libxray')
assert modules==set((root/'Core/modules.lock.txt').read_text().splitlines()), 'Probe dependency graph differs from pinned upstream'
if args.test or args.race:
 command=[str(go),'test','-mod=readonly',f'-overlay={manifest}','-count=1']
 if args.race:command+=['-race']
 subprocess.run(command+['.'],cwd=module,env=env,check=True)
 raise SystemExit(0)
targets=[('macosx','darwin','arm64','arm64','15.0')]
if not args.mac_only:
 targets += [('macosx','darwin','amd64','x86_64','15.0'),('iphoneos','ios','arm64','arm64','15.0'),('iphonesimulator','ios','arm64','arm64','15.0'),('iphonesimulator','ios','amd64','x86_64','15.0'),('appletvos','ios','arm64','arm64','18.0'),('appletvsimulator','ios','arm64','arm64','18.0'),('appletvsimulator','ios','amd64','x86_64','18.0')]
products={}
for sdk,goos,goarch,arch,minimum in targets:
 out=work/f'{sdk}-{arch}';out.mkdir(exist_ok=True)
 sdkpath=subprocess.check_output(['xcrun','--sdk',sdk,'--show-sdk-path'],text=True).strip()
 flags=f'-isysroot {sdkpath} -m{sdk}-version-min={minimum} -arch {arch}'
 buildenv=dict(env,GOOS=goos,GOARCH=goarch,CGO_ENABLED='1',CC=f'xcrun --sdk {sdk} clang',CXX=f'xcrun --sdk {sdk} clang++',CGO_CFLAGS=flags,CGO_CXXFLAGS=flags,CGO_LDFLAGS=flags,DARWIN_SDK=sdk)
 subprocess.run([str(go),'build','-mod=readonly',f'-overlay={manifest}',f'-tags={goos}','-trimpath','-ldflags=-s -w -buildid=','-buildmode=c-archive','-o',str(out/'libXray.a'),'.'],cwd=module,env=buildenv,check=True)
 (out/'module.modulemap').write_text('module ProbeCore {\n header "libXray.h"\n export *\n}\n')
 products.setdefault(sdk,[]).append(out)
 print('Built probe core:',sdk,arch,flush=True)
native=root/'Artifacts/ProbeNativeSmoke';native.mkdir(exist_ok=True)
for name in ['libXray.a','libXray.h','module.modulemap']:shutil.copy2(work/'macosx-arm64'/name,native/name)
destination=native
if not args.mac_only:
 command=['xcodebuild','-create-xcframework']
 for sdk,paths in products.items():
  directory=paths[0]
  if len(paths)>1:
   directory=work/(sdk+'-universal');directory.mkdir(exist_ok=True)
   subprocess.run(['lipo','-create',*[str(p/'libXray.a') for p in paths],'-output',str(directory/'libXray.a')],check=True)
   for name in ['libXray.h','module.modulemap']:shutil.copy2(paths[0]/name,directory/name)
  # A distinct static framework avoids Xcode's shared libXray.a/include outputs
  # colliding with the unchanged tunnel XCFramework in the same build graph.
  framework=directory/'ProbeCore.framework'
  headers=framework/'Headers';headers.mkdir(parents=True,exist_ok=True)
  modules_dir=framework/'Modules';modules_dir.mkdir(exist_ok=True)
  shutil.copy2(directory/'libXray.a',framework/'ProbeCore')
  shutil.copy2(directory/'libXray.h',headers/'ProbeCore.h')
  (modules_dir/'module.modulemap').write_text('framework module ProbeCore {\n umbrella header "ProbeCore.h"\n export *\n}\n')
  (framework/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'app.leadvpn.link.probecore','CFBundleName':'ProbeCore','CFBundleExecutable':'ProbeCore','CFBundlePackageType':'FMWK','CFBundleShortVersionString':'1.0','CFBundleVersion':'1'}))
  command+=['-framework',str(framework)]
 destination=root/'Artifacts/ProbeCore.xcframework'
 if destination.exists():shutil.rmtree(destination)
 subprocess.run(command+['-output',str(destination)],check=True)
for artifact in ([native] if args.mac_only else [native,destination]):
 provenance={'go':version,'libxrayCommit':lock['libxray']['commit'],'xrayModule':lock['xray_core']['module_version'],'isolationPatchSHA256':hashlib.sha256((module/'isolation.patch').read_bytes()).hexdigest(),'upstreamFiles':files,'adapterSHA256':hashlib.sha256((module/'main.go').read_bytes()).hexdigest(),'adapterSources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in module.glob('*.go') if not p.name.endswith('_test.go')},'moduleFiles':{n:hashlib.sha256((module/n).read_bytes()).hexdigest() for n in ['go.mod','go.sum']},'files':{str(p.relative_to(artifact)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifact.rglob('*') if p.is_file()}}
 (root/'Artifacts'/(artifact.name+'.provenance.json')).write_text(json.dumps(provenance,indent=2)+'\n')
