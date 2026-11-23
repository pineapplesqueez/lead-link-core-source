# App-only parallel profile core

Lead Link runs at most eight complete Xray profiles concurrently (`maximumProbes`, equal to `ProfileLatencyProbe.concurrency`) for HTTPS latency checks. Each has its own `core.Instance`, authenticated loopback SOCKS inbound, DNS client, outbound manager, routing and observers. The application links **ProbeCore**; PacketTunnel targets continue to link the original **LibXray**. Each process embeds exactly one Go runtime.

`main.go` adds four internal Invoke v3 methods: `leadlink.startProbe` returns an opaque ownership token, `leadlink.stopProbe` closes only that token, `leadlink.probeState` reports active/peak instance counts, and `leadlink.probeObservation` returns readiness/revision/budget for that token. Observation responses contain no tags, URLs, keys or native errors. Existing methods delegate to pinned libXray. Managed start/test/ping operations are rejected while probes exist; probe start rejects an existing managed runtime. Lifecycle mutations are serialized, while the requests and observers run concurrently. The limit is enforced in the model, Swift worker pool and Go adapter.

On iOS 17 and newer, URLSession uses Apple’s mandatory authenticated SOCKS proxy configuration. On iOS 15 and 16, the adapter sends each request through the same per-profile listener with Go’s SOCKS5 HTTP transport. Both paths require HTTP 204, verify HTTPS certificates and stop on redirects.

## macOS sandbox entitlement

Each probe listens on `127.0.0.1` with an ephemeral port and per-probe SOCKS credentials, and the app's URLSession connects to it. In the macOS App Sandbox this needs `com.apple.security.network.server` in addition to `network.client`: checked on 19 November 2026 with an ad-hoc signed sandboxed binary, `bind()` on `127.0.0.1` fails with `EPERM` without it and succeeds with it. Keep the entitlement on the macOS app (not the tunnel extension) while the probe uses a loopback inbound; TV reception runs only on tvOS and does not need it.

## Isolation overlay

This is an app-only adaptation of the pinned upstream, not the old Lead VPN patch set. `isolation.patch` changes eight Xray files:

- Bind system DNS and `dialerProxy` lookup to the owning instance through context, including freedom UDP and target resolution.
- Preserve that context across detached, gRPC and XHTTP dialing contexts.
- Remove each instance's gRPC/XHTTP cache entries and close its connections on cancellation. XHTTP raw upload sockets and idle clients are included.
- Apply the shared, trusted asset directory only with an empty pool; skip per-instance global environment reload.
- Close partially constructed isolated instances on construction failure.
- Return a deep snapshot under the ordinary observer's existing status lock. The upstream getter exposed concurrently mutated status pointers; the new concurrent polling test reproduced this with Go's race detector. Burst observation already snapshots its data under a lock.

No routing rules, outbound tags, balance strategies, fallback tags or observer selectors are replaced. The request follows the profile's policy: a direct rule for the HTTPS endpoint yields a direct-route measurement. Existing compiler restrictions on unsupported profiles still apply.

The first request starts immediately with its five-second budget. For a used, observed balancer that initially has incomplete health information, a failed/timed-out request and a transition to usable observations grant **one** fresh request through the unchanged router, using a new URLSession so an old SOCKS/HTTP2 connection cannot pin it to the dead outbound. Readiness alone never cancels an in-flight request: a healthy slow handshake must be allowed to finish. Each attempt has its own completion signal; late callbacks cannot finish the next attempt. A successful HTTP 204 remains required. Observation readiness itself never reports success, and there is no fixed warmup delay.

Observation waiting is bounded by twice the configured burst timeout (default 2 × 5s, capped at 10s), or 10s for ordinary observatory, plus 250ms to publish results; burst may perform a second direct-connectivity check before publishing failure. It is also capped at twice the requested timeout plus 250ms. The request after recovery gets up to another five seconds. Default burst and ordinary observation have a 15.25s network/warmup bound, excluding core startup/cleanup and queue time. Healthy requests finish immediately. Custom very slow or sequential provider observers can still exceed these bounded waits; we do not change their intervals, selectors or concurrency. The probe returns the duration of the successful request, excluding the wait. The app displays an estimated latency by dividing those milliseconds by 3.3 and rounding to the nearest millisecond, with a minimum of 1 ms.

`upstream-files.json` pins the original input hashes. The build copies upstream into `.build`, applies a Go overlay and leaves Vendor, the module cache and the tunnel binary unchanged. The Go module graph must match `Core/modules.lock.txt` apart from this wrapper. Upgrade upstream only after reviewing the overlay against the new source and rerunning isolation tests.

## Build and checks

Prepare the original core/toolchain as described in `../INTEGRATION.md`, then:

```sh
python3 scripts/build-probe-core.py --test --race
python3 scripts/build-probe-core.py
python3 scripts/verify-core.py --probe
python3 scripts/verify-runtime.py --xray Artifacts/TestServer/xray --security reality
python3 scripts/verify-balancer-failover.py
python3 scripts/verify-model.py
./scripts/verify.sh
```

The test server is built by `scripts/build-core.py --go .cache/toolchains/go-1.27.3/go/bin/go --mac-only --test-server`. Go tests use only synthetic local configurations. Tests cover identical tags with distinct DNS/route/chain behavior, gRPC/XHTTP DNS isolation, rejected fourth start, managed overlap, failed start, cancellation/refill and independent cleanup. Swift tests exercise three simultaneous full profiles with direct/leastPing/leastLoad rules and cancellation through the actual URLSession/SOCKS path.

Outputs: `Artifacts/ProbeCore.xcframework` (five SDK variants, eight architecture/platform combinations) and `Artifacts/ProbeNativeSmoke`. Provenance records adapter/patch/module hashes, pinned versions and artifact hashes. The static framework has a distinct module/product name so Xcode never combines or overwrites it with LibXray. `--mac-only` builds the native test archive only.

Debug apps accept `--e5-parallel-probe-smoke`: five synthetic full profiles request Google's HTTPS 204 endpoint with the worker limit, check that the peak equals the number of profiles (at most the limit) and the final count is zero, emit a numeric/boolean report and exit. These include direct, leastPing, leastLoad and dead-primary/random fallback with both ordinary and burst observation. It does not read the catalog or configure VPN. `scripts/verify-live-probe.py` instead checks saved profiles via the signed app's private pipe and reports batch wall time, not the sum of overlapping durations.

The overlay modifies MPL-2.0 Xray source. Preserve the original notices and make the corresponding modified source (pinned upstream plus this overlay) available with distributions as applicable. This does not choose a license for the rest of Lead Link.
