package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"golang.org/x/net/proxy"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func invokeTest(t *testing.T, method string, payload map[string]any) map[string]any {
	t.Helper()
	b, _ := json.Marshal(map[string]any{"apiVersion": 3, "method": method, "payload": payload})
	var r map[string]any
	if e := json.Unmarshal([]byte(invoke(string(b))), &r); e != nil {
		t.Fatal(e)
	}
	return r
}
func freePort(t *testing.T) int {
	t.Helper()
	l, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	p := l.Addr().(*net.TCPAddr).Port
	l.Close()
	return p
}
func startTestProbe(t *testing.T, root map[string]any, assets string) (string, int) {
	t.Helper()
	p := freePort(t)
	root["env"] = map[string]string{"xray.location.asset": assets}
	root["inbounds"] = []any{map[string]any{"tag": "input", "protocol": "socks", "listen": "127.0.0.1", "port": p, "settings": map[string]any{"auth": "password", "accounts": []any{map[string]string{"user": "fixture", "pass": "fixture"}}}}}
	b, _ := json.Marshal(root)
	r := invokeTest(t, "leadlink.startProbe", map[string]any{"xrayJson": string(b)})
	if r["success"] != true {
		t.Fatal("start rejected")
	}
	return r["data"].(map[string]any)["probeID"].(string), p
}
func stopTestProbe(t *testing.T, id string) {
	t.Helper()
	if invokeTest(t, "leadlink.stopProbe", map[string]any{"probeID": id})["success"] != true {
		t.Error("stop rejected")
	}
}
func requestVia(port int, dest string) (string, error) {
	d, e := proxy.SOCKS5("tcp", fmt.Sprintf("127.0.0.1:%d", port), &proxy.Auth{User: "fixture", Password: "fixture"}, &net.Dialer{Timeout: time.Second})
	if e != nil {
		return "", e
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	conn, e := d.(proxy.ContextDialer).DialContext(ctx, "tcp", dest)
	if e != nil {
		return "", e
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(2 * time.Second))
	fmt.Fprintf(conn, "GET / HTTP/1.1\r\nHost: fixture.test\r\nConnection: close\r\n\r\n")
	response, e := http.ReadResponse(bufio.NewReader(conn), nil)
	if e != nil {
		return "", e
	}
	defer response.Body.Close()
	b, e := io.ReadAll(response.Body)
	return string(b), e
}
func TestThreeIndependentDNSRoutesAndChains(t *testing.T) {
	assets := t.TempDir()
	a, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	defer a.Close()
	port := a.Addr().(*net.TCPAddr).Port
	b, e := net.Listen("tcp6", fmt.Sprintf("[::1]:%d", port))
	if e != nil {
		t.Fatal(e)
	}
	defer b.Close()
	sa := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "PROFILE_A") })}
	defer sa.Close()
	go sa.Serve(a)
	sb := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "PROFILE_B") })}
	defer sb.Close()
	go sb.Serve(b)
	config := func(ip string) map[string]any {
		return map[string]any{
			"dns":       map[string]any{"hosts": map[string]string{"fixture.test": ip}, "servers": []any{}},
			"outbounds": []any{map[string]any{"tag": "blocked", "protocol": "blackhole"}, map[string]any{"tag": "direct", "protocol": "freedom", "settings": map[string]string{"domainStrategy": "UseIP"}}},
			"routing":   map[string]any{"rules": []any{map[string]any{"type": "field", "domain": []string{"full:fixture.test"}, "outboundTag": "direct"}}},
		}
	}
	ca, cb, cc := config("127.0.0.1"), config("::1"), config("127.0.0.1")
	// Third profile routes through a chained outbound with the same tag names.
	cc["outbounds"] = []any{map[string]any{"tag": "direct", "protocol": "freedom", "streamSettings": map[string]any{"sockopt": map[string]string{"dialerProxy": "chain"}}}, map[string]any{"tag": "chain", "protocol": "freedom", "settings": map[string]string{"redirect": fmt.Sprintf("[::1]:%d", port)}}}
	idA, pA := startTestProbe(t, ca, assets)
	defer func() {
		if idA != "" {
			stopTestProbe(t, idA)
		}
	}()
	idB, pB := startTestProbe(t, cb, assets)
	defer stopTestProbe(t, idB)
	idC, pC := startTestProbe(t, cc, assets)
	defer stopTestProbe(t, idC)
	// Fill the remaining slots; one more start beyond the limit is refused.
	for i := 3; i < maximumProbes; i++ {
		id, _ := startTestProbe(t, config("127.0.0.1"), assets)
		defer stopTestProbe(t, id)
	}
	// A valid configuration on a free port: only the limit can refuse it.
	extra := config("127.0.0.1")
	extra["env"] = map[string]string{"xray.location.asset": assets}
	extra["inbounds"] = []any{map[string]any{"tag": "input", "protocol": "socks", "listen": "127.0.0.1", "port": freePort(t), "settings": map[string]any{"auth": "password", "accounts": []any{map[string]string{"user": "fixture", "pass": "fixture"}}}}}
	encoded, _ := json.Marshal(extra)
	if invokeTest(t, "leadlink.startProbe", map[string]any{"xrayJson": string(encoded)})["success"] != false {
		t.Fatal("probe beyond the limit accepted")
	}
	if invokeTest(t, "runXray", map[string]any{"xrayJson": `{"outbounds":[{"protocol":"blackhole"}]}`})["success"] != false {
		t.Fatal("managed overlap accepted")
	}
	var wg sync.WaitGroup
	for _, item := range []struct {
		port int
		want string
	}{{pA, "PROFILE_A"}, {pB, "PROFILE_B"}, {pC, "PROFILE_B"}} {
		wg.Add(1)
		go func(p int, want string) {
			defer wg.Done()
			for i := 0; i < 10; i++ {
				got, e := requestVia(p, fmt.Sprintf("fixture.test:%d", port))
				if e != nil || !contains(got, want) {
					t.Errorf("route mismatch: expected %s; err %v", want, e)
					return
				}
			}
		}(item.port, item.want)
	}
	wg.Wait()
	stopTestProbe(t, idA)
	idA = ""
	if got, e := requestVia(pB, fmt.Sprintf("fixture.test:%d", port)); e != nil || !contains(got, "PROFILE_B") {
		t.Fatal("stopping A damaged B", e)
	}
	idD, pD := startTestProbe(t, config("127.0.0.1"), assets)
	defer stopTestProbe(t, idD)
	if got, e := requestVia(pD, fmt.Sprintf("fixture.test:%d", port)); e != nil || !contains(got, "PROFILE_A") {
		t.Fatal("refill failed", e)
	}
	if invokeTest(t, "leadlink.stopProbe", map[string]any{"probeID": "unknown"})["success"] != false {
		t.Fatal("unknown stop accepted")
	}
}
func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func TestRejectedStartDoesNotLeakSlot(t *testing.T) {
	assets := t.TempDir()
	root := map[string]any{"outbounds": []any{map[string]any{"protocol": "freedom"}}}
	id, _ := startTestProbe(t, root, assets)
	stopTestProbe(t, id)
	in := root["inbounds"].([]any)[0].(map[string]any)
	listener, e := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", in["port"]))
	if e != nil {
		t.Fatal(e)
	}
	defer listener.Close()
	data, _ := json.Marshal(root)
	if invokeTest(t, "leadlink.startProbe", map[string]any{"xrayJson": string(data)})["success"] != false {
		t.Fatal("busy port accepted")
	}
	root["routing"] = map[string]any{"rules": []any{map[string]any{"type": "field", "network": "tcp", "outboundTag": "missing"}}}
	root["outbounds"] = []any{map[string]any{"protocol": "invalid"}}
	data, _ = json.Marshal(root)
	if invokeTest(t, "leadlink.startProbe", map[string]any{"xrayJson": string(data)})["success"] != false {
		t.Fatal("invalid profile accepted")
	}
	state := invokeTest(t, "leadlink.probeState", nil)["data"].(map[string]any)
	if state["active"] != float64(0) {
		t.Fatal("failed start leaked a slot")
	}
	for i := 0; i < 3; i++ {
		id, _ := startTestProbe(t, map[string]any{"outbounds": []any{map[string]any{"protocol": "freedom"}}}, assets)
		defer stopTestProbe(t, id)
	}
}

// Real XHTTP/gRPC servers live in another process. Each client uses the same
// remote hostname, outbound tags and service/path but different profile DNS.
func TestTransportDNSIsolation(t *testing.T) {
	executable, err := filepath.Abs("../../Artifacts/TestServer/xray")
	if err != nil {
		t.Fatal(err)
	}
	for _, network := range []string{"grpc", "xhttp"} {
		t.Run(network, func(t *testing.T) {
			assets := t.TempDir()
			result := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "TRANSPORT_OK") }))
			defer result.Close()
			destination := strings.TrimPrefix(result.URL, "http://")
			serverPort := freePort(t)
			stream := map[string]any{"network": network, "security": "none"}
			if network == "grpc" {
				stream["grpcSettings"] = map[string]any{"serviceName": "probe"}
			} else {
				stream["xhttpSettings"] = map[string]any{"path": "/probe", "mode": "packet-up"}
			}
			uuid := "00000000-0000-4000-8000-000000000001"
			server := map[string]any{"log": map[string]string{"loglevel": "none"}, "inbounds": []any{map[string]any{"listen": "127.0.0.1", "port": serverPort, "protocol": "vless", "settings": map[string]any{"clients": []any{map[string]string{"id": uuid}}, "decryption": "none"}, "streamSettings": stream}}, "outbounds": []any{map[string]any{"protocol": "freedom", "settings": map[string]any{"finalRules": []any{map[string]any{"action": "allow", "ip": []string{"127.0.0.1/32"}, "port": strings.Split(destination, ":")[1]}}}}}}
			raw, _ := json.Marshal(server)
			path := filepath.Join(assets, "server.json")
			if e := os.WriteFile(path, raw, 0600); e != nil {
				t.Fatal(e)
			}
			cmd := exec.Command(executable, "run", "-config", path)
			if e := cmd.Start(); e != nil {
				t.Fatal(e)
			}
			defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
			for i := 0; i < 100; i++ {
				c, e := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", serverPort), time.Millisecond*50)
				if e == nil {
					c.Close()
					break
				}
				time.Sleep(time.Millisecond * 20)
			}
			config := func(ip string) map[string]any {
				st := map[string]any{}
				for k, v := range stream {
					st[k] = v
				}
				st["sockopt"] = map[string]string{"domainStrategy": "ForceIP"}
				return map[string]any{"dns": map[string]any{"hosts": map[string]string{"transport.test": ip}, "servers": []any{}}, "outbounds": []any{map[string]any{"protocol": "vless", "tag": "proxy", "settings": map[string]any{"vnext": []any{map[string]any{"address": "transport.test", "port": serverPort, "users": []any{map[string]string{"id": uuid, "encryption": "none"}}}}}, "streamSettings": st}}}
			}
			idA, pA := startTestProbe(t, config("127.0.0.1"), assets)
			defer stopTestProbe(t, idA)
			idB, pB := startTestProbe(t, config("127.0.0.2"), assets)
			defer stopTestProbe(t, idB)
			idC, pC := startTestProbe(t, config("127.0.0.1"), assets)
			defer stopTestProbe(t, idC)
			var wg sync.WaitGroup
			for _, entry := range []struct {
				p  int
				ok bool
			}{{pA, true}, {pB, false}, {pC, true}} {
				wg.Add(1)
				go func(p int, ok bool) {
					defer wg.Done()
					for i := 0; i < 2; i++ {
						got, e := requestVia(p, destination)
						success := e == nil && contains(got, "TRANSPORT_OK")
						if success != ok {
							t.Errorf("%s isolation failed: expected success %v, err %v", network, ok, e)
						}
					}
				}(entry.p, entry.ok)
			}
			wg.Wait()
		})
	}
}
