// Legacy iOS has no URLSession API for mandatory authenticated SOCKS5.
// Each request uses the private listener belonging to its own probe instance.
package main

import "C"
import (
	"context"
	"crypto/tls"
	"errors"
	"net"
	"net/http"
	"net/url"
	"runtime/cgo"
	"time"
)

type httpProbe struct {
	ctx    context.Context
	cancel context.CancelFunc
	proxy  *url.URL
}

//export CGoNewProbeRequest
func CGoNewProbeRequest(id *C.char) C.ulonglong {
	lifecycle.Lock()
	defer lifecycle.Unlock()
	p, ok := probes[C.GoString(id)]
	if !ok {
		return 0
	}
	ctx, cancel := context.WithCancel(p.ctx)
	return C.ulonglong(cgo.NewHandle(&httpProbe{ctx, cancel, p.proxyURL}))
}

//export CGoCancelProbeRequest
func CGoCancelProbeRequest(handle C.ulonglong) {
	cgo.Handle(handle).Value().(*httpProbe).cancel()
}

//export CGoFreeProbeRequest
func CGoFreeProbeRequest(handle C.ulonglong) {
	CGoCancelProbeRequest(handle)
	cgo.Handle(handle).Delete()
}

//export CGoRunProbeRequest
func CGoRunProbeRequest(handle C.ulonglong, endpoint *C.char, milliseconds C.int) C.int {
	p := cgo.Handle(handle).Value().(*httpProbe)
	ctx, cancel := context.WithTimeout(p.ctx, time.Duration(milliseconds)*time.Millisecond)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, C.GoString(endpoint), nil)
	if err != nil {
		return -1000
	}
	if req.URL.Scheme != "https" && !(req.URL.Scheme == "http" && req.URL.Hostname() == "probe.invalid") {
		return -1002
	}
	req.Header.Set("Cache-Control", "no-cache")
	transport := &http.Transport{Proxy: http.ProxyURL(p.proxy), DisableKeepAlives: true, MaxResponseHeaderBytes: 65536}
	defer transport.CloseIdleConnections()
	// RoundTrip returns the first response without following redirects or reading a body.
	res, err := transport.RoundTrip(req)
	if err != nil {
		var timeout net.Error
		var certificate *tls.CertificateVerificationError
		switch {
		case errors.Is(err, context.Canceled):
			return -999
		case errors.As(err, &certificate):
			return -1202
		case errors.As(err, &timeout) && timeout.Timeout():
			return -1001
		default:
			return -1005
		}
	}
	defer res.Body.Close()
	return C.int(res.StatusCode)
}
