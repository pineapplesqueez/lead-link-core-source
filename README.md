<div align="center">
  <img src="assets/lead-link.png" width="96" height="96" alt="Lead Link icon">
  <h1>Lead Link Core</h1>
  <p>Pinned Xray sources, the native bridge, and the Lead Link probe adapter.</p>
  <p><strong>English</strong> · <a href="README.ru.md">Русский</a></p>
  <p><a href="https://lead-link.app/en/">Website</a> · <a href="https://lead-link.app/en/support/">Support</a> · <a href="https://github.com/pineapplesqueez/lead-link-core-source/releases">Source releases</a></p>
  <p><strong>iOS · macOS · tvOS</strong></p>
</div>

---

This repository provides the corresponding source for the core components used in **Lead Link**, maintained by **ADAPTA SIA**. It includes the original tunnel core and the modified core used for concurrent profile latency checks.

The source here matches the core in **Lead Link 1.0.0 (8)**. Documentation updates do not imply a new application build or a newer upstream core.

> This is a core source distribution, not the complete Lead Link application or an installable VPN client. The app's interface, storage layer, and TV transfer implementation are outside this package.

## Explore the source

| Path | What it contains |
| --- | --- |
| [Xray-core-original](Xray-core-original/) | Unmodified Xray-core used by the VPN extension. |
| [libXray](libXray/) | The upstream native bridge and Invoke API. |
| [Xray-core-probe](Xray-core-probe/) | Xray-core with the Lead Link isolation changes already applied. |
| [ProbeCore](ProbeCore/) | The app's Go probe adapter, tests, patch, and upstream file hashes. |
| [build-scripts](build-scripts/) | Scripts for the pinned toolchain, core builds, verification, and license notices. |
| [ThirdPartyNotices.txt](ThirdPartyNotices.txt) | Notices for the core dependencies, Go, and geodata. |
| [SHA256SUMS.json](SHA256SUMS.json) | SHA-256 hashes of every packaged file except the manifest itself. |

## Pinned versions

| Component | Version |
| --- | --- |
| Xray-core | **v26.10.31** · commit [`a4a3dff5b20c`](https://github.com/XTLS/Xray-core/commit/a4a3dff5b20c) |
| libXray | Commit [`7fe8528063e54343af8ba9a37431afc56000de21`](https://github.com/XTLS/libXray/commit/7fe8528063e54343af8ba9a37431afc56000de21) |
| Go | **1.27.3** |
| Xray isolation overlay | **8 modified files**, used by ProbeCore only |

The authoritative records are [upstream.lock.json](upstream.lock.json), [modules.lock.txt](modules.lock.txt), and [go-toolchain.lock.json](go-toolchain.lock.json). They pin the sources and dependency graph rather than following upstream `main`.

## Tunnel and latency checks

**VPN extension → original LibXray / Xray-core.** The tunnel uses the unmodified upstream core.

**Application → ProbeCore / isolated Xray-core.** Latency checks run separate full profile instances with their own loopback SOCKS listener, DNS, routing, and observers. The overlay isolates instance state and cleanup; it does not replace routing rules or balancer strategies. A profile's direct route can therefore produce a direct-route measurement.

The app and extension run in separate processes, each with one Go runtime. On macOS, the app needs `com.apple.security.network.server` for the authenticated loopback listener used by the probe. See the [ProbeCore technical notes](ProbeCore/README.md) for limits, lifecycle, and sandbox details.

To inspect the changes, open the [isolation patch](ProbeCore/isolation.patch), the [original file hashes](ProbeCore/upstream-files.json), or compare the two Xray trees:

```sh
git diff --no-index -- Xray-core-original Xray-core-probe
```

Exit status `1` is expected when `git diff` finds the documented differences.

## Verify a snapshot

Run this from the root of an extracted source package or repository checkout:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

expected = json.loads(Path("SHA256SUMS.json").read_text())
failed = [name for name, digest in expected.items()
          if not Path(name).is_file()
          or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
if failed:
    raise SystemExit("Missing or changed files:\n" + "\n".join(failed))
print(f"Verified {len(expected)} files.")
PY
```

The [LibXray](LibXray.xcframework.provenance.json) and [ProbeCore](ProbeCore.xcframework.provenance.json) provenance records describe the original build inputs and artifact hashes. Locally rebuilt binaries can differ with the toolchain and environment; the source manifest verifies the source snapshot.

## Build the core components

The supplied bootstrap targets **Apple Silicon macOS**. You need **Python 3.12+**, a selected Xcode installation with iOS, macOS, and tvOS SDKs, and network access for the pinned toolchain and Go dependencies. The recorded build used Xcode 27.2; deployment targets are checked by `verify-core.py`.

The scripts expect the application's build directory layout. Use a separate workspace so build outputs do not modify this source snapshot.

<details>
<summary><strong>Workspace setup and build commands</strong></summary>

From the root of this repository:

```sh
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/lead-link-core-build.XXXXXX")"
mkdir -p "$build_dir/Core" "$build_dir/scripts"
cp -R ProbeCore "$build_dir/Core/ProbeCore"
cp -R GeodataLicenses "$build_dir/Core/GeodataLicenses"
cp upstream.lock.json modules.lock.txt licenses.lock.json \
  go-toolchain.lock.json geodata.lock.json "$build_dir/Core/"
cp build-scripts/*.py "$build_dir/scripts/"
cd "$build_dir"
```

Fetch and verify the pinned toolchain and the complete official libXray archive, then build both core variants:

```sh
python3 scripts/bootstrap-go.py
python3 scripts/fetch-core.py
python3 scripts/verify-upstream.py
python3 scripts/build-core.py --go .cache/toolchains/go-1.27.3/go/bin/go
python3 scripts/verify-core.py
python3 scripts/build-probe-core.py --test --race
python3 scripts/build-probe-core.py
python3 scripts/verify-core.py --probe
```

`build-core.py` downloads and verifies the locked Go modules. `build-probe-core.py` applies the isolation overlay in its build workspace, leaving the tunnel sources unchanged.

Outputs are `Artifacts/LibXray.xcframework` and `Artifacts/ProbeCore.xcframework`, plus build provenance. Each XCFramework covers five SDK variants across eight platform/architecture combinations.

</details>

The [integration notes](INTEGRATION.md) (Russian) and [ProbeCore notes](ProbeCore/README.md) provide further context. Some app-level checks mentioned there require the separate application workspace. This package does not include an app Xcode project, Apple signing credentials, prebuilt frameworks, or an offline toolchain.

## Licenses and attribution

- **Xray-core:** [MPL-2.0](Xray-core-original/LICENSE). The eight modified Xray files remain under [MPL-2.0](Xray-core-probe/LICENSE), with their existing notices preserved.
- **libXray:** [MIT](libXray/LICENSE).
- **Other components:** consult [ThirdPartyNotices.txt](ThirdPartyNotices.txt), [licenses.lock.json](licenses.lock.json), [GeodataLicenses](GeodataLicenses/), and the notices in individual files. This repository does not assign one blanket license to every component.

The modified Xray source is published here directly, alongside its patch and original version. Publication of this package does not grant a license to the separate Lead Link application source or branding. See the [Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/) for guidance on distributing MPL-covered code.

## Snapshot history

| Snapshot | Scope |
| --- | --- |
| Documentation update · 20 November 2026 | English and Russian README pages, repository presentation, and the macOS loopback entitlement explanation. Core code unchanged. |
| [source-audit-2026-11-17](https://github.com/pineapplesqueez/lead-link-core-source/releases/tag/source-audit-2026-11-17) | Completed source inventory and nested dependency notices; fixed files omitted by upstream ignore rules. |
| [build-0.1.0-4](https://github.com/pineapplesqueez/lead-link-core-source/tree/build-0.1.0-4) | Historical source snapshot, retained for traceability. |

Tags identify source snapshots; their names do not necessarily match the latest app version. Historical tags and release archives retain the documentation that shipped with them.

## Support

For Lead Link questions, use [support](https://lead-link.app/en/support/). When reporting a core issue, include the source commit or tag, platform, and a minimal configuration with all credentials removed. Do not post subscription URLs, keys, user profiles, or Apple signing material in public issues.
