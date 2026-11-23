// Lead Link app-only probe adapter. The VPN extension links untouched libXray.
package main

/*
#include <stdlib.h>
*/
import "C"
import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	lib "github.com/xtls/libxray"
	"github.com/xtls/libxray/memory"
	lx "github.com/xtls/libxray/xray"
	"github.com/xtls/xray-core/common/platform"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/transport/internet"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"unsafe"
)

type probeEntry struct {
	core     *core.Instance
	cancel   context.CancelFunc
	health   *probeHealth
	ctx      context.Context
	proxyURL *url.URL
}

// Concurrent probe instances. Keep equal to ProfileLatencyProbe.concurrency.
const maximumProbes = 8

var lifecycle sync.Mutex
var probes = map[string]probeEntry{}
var assets string
var maximumActive int

func failure() string { return `{"success":false,"data":null,"error":"probe operation rejected"}` }
func response(value any) string {
	b, e := json.Marshal(map[string]any{"success": true, "data": value, "error": ""})
	if e != nil {
		return failure()
	}
	return string(b)
}

type request struct {
	APIVersion int    `json:"apiVersion"`
	Method     string `json:"method"`
	Payload    struct {
		JSON string `json:"xrayJson"`
		ID   string `json:"probeID"`
	} `json:"payload"`
}

func invoke(text string) string {
	if len(text) > 16*1024*1024 {
		return failure()
	}
	var r request
	if json.Unmarshal([]byte(text), &r) != nil || r.APIVersion != 3 {
		return failure()
	}
	lifecycle.Lock()
	defer lifecycle.Unlock()
	switch r.Method {
	case "leadlink.startProbe":
		id, e := startProbe(r.Payload.JSON)
		if e != nil {
			return failure()
		}
		return response(map[string]any{"probeID": id})
	case "leadlink.stopProbe":
		p, ok := probes[r.Payload.ID]
		if !ok {
			return failure()
		}
		p.cancel()
		err := p.core.Close()
		delete(probes, r.Payload.ID)
		if err != nil {
			return failure()
		}
		return response(struct{}{})
	case "leadlink.probeObservation":
		p, ok := probes[r.Payload.ID]
		if !ok {
			return failure()
		}
		value, err := p.health.observation(p.core)
		if err != nil {
			return failure()
		}
		return response(value)
	case "leadlink.probeState":
		return response(map[string]any{"active": len(probes), "maximumActive": maximumActive})
	default:
		if len(probes) > 0 && r.Method != "xrayVersion" && r.Method != "getXrayState" {
			return failure()
		}
		return lib.Invoke(text)
	}
}
func startProbe(text string) (string, error) {
	reject := errors.New("invalid probe")
	if len(probes) >= maximumProbes || lx.GetXrayState() || len(text) > 2*1024*1024 {
		return "", reject
	}
	var root map[string]json.RawMessage
	if json.Unmarshal([]byte(text), &root) != nil {
		return "", reject
	}
	var env map[string]string
	if json.Unmarshal(root["env"], &env) != nil || len(env) != 1 || env["xray.location.asset"] == "" {
		return "", reject
	}
	asset := env["xray.location.asset"]
	if len(probes) > 0 && assets != asset {
		return "", reject
	}
	var inbounds []struct {
		Listen, Protocol string
		Port             int
		Settings         struct {
			Auth     string
			Accounts []struct{ User, Pass string }
		}
	}
	if json.Unmarshal(root["inbounds"], &inbounds) != nil || len(inbounds) != 1 {
		return "", reject
	}
	in := inbounds[0]
	if in.Listen != "127.0.0.1" || in.Protocol != "socks" || in.Port < 1 || in.Port > 65535 || in.Settings.Auth != "password" || len(in.Settings.Accounts) != 1 || in.Settings.Accounts[0].User == "" || in.Settings.Accounts[0].Pass == "" {
		return "", reject
	}
	if len(probes) == 0 {
		if os.Setenv("xray.location.asset", asset) != nil {
			return "", reject
		}
		if platform.ReloadEnvSettings() != nil {
			return "", reject
		}
		assets = asset
		memory.InitForceFree()
	}
	delete(root, "env")
	root["log"] = json.RawMessage(`{"loglevel":"none","access":"none","error":"none","dnsLog":false}`)
	encoded, e := json.Marshal(root)
	if e != nil {
		return "", reject
	}
	config, e := core.LoadConfig("json", strings.NewReader(string(encoded)))
	if e != nil {
		return "", reject
	}
	ctx, cancel := context.WithCancel(context.Background())
	state := internet.NewInstanceDialer(ctx)
	instance, e := core.NewWithContext(internet.ContextWithInstanceDialer(ctx, state), config)
	if e != nil {
		cancel()
		return "", reject
	}
	if e = instance.Start(); e != nil {
		cancel()
		_ = instance.Close()
		return "", reject
	}
	var raw [16]byte
	if _, e = rand.Read(raw[:]); e != nil {
		cancel()
		_ = instance.Close()
		return "", reject
	}
	id := hex.EncodeToString(raw[:])
	probes[id] = probeEntry{core: instance, cancel: cancel, health: newProbeHealth(root), ctx: ctx, proxyURL: &url.URL{Scheme: "socks5h", Host: "127.0.0.1:" + strconv.Itoa(in.Port), User: url.UserPassword(in.Settings.Accounts[0].User, in.Settings.Accounts[0].Pass)}}
	if len(probes) > maximumActive {
		maximumActive = len(probes)
	}
	return id, nil
}
func main() {}

//export CGoInvoke
func CGoInvoke(input *C.char) *C.char { return C.CString(invoke(C.GoString(input))) }

//export CGoFree
func CGoFree(value *C.char) { C.free(unsafe.Pointer(value)) }
