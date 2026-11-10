package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

func healthFixture(strategy string, fallback string, observe []string) *probeHealth {
	b := map[string]any{"tag": "auto", "strategy": map[string]string{"type": strategy}, "selector": []string{"proxy-"}}
	if fallback != "" {
		b["fallbackTag"] = fallback
	}
	data, _ := json.Marshal(map[string]any{
		"outbounds":        []any{map[string]string{"tag": "proxy-a", "protocol": "vless"}, map[string]string{"tag": "proxy-b", "protocol": "vless"}, map[string]string{"tag": "backup", "protocol": "vless"}, map[string]string{"tag": "blocked", "protocol": "blackhole"}},
		"routing":          map[string]any{"rules": []any{map[string]string{"balancerTag": "auto"}}, "balancers": []any{b}},
		"burstObservatory": map[string]any{"subjectSelector": observe, "pingConfig": map[string]string{"timeout": "5s"}},
	})
	var root map[string]json.RawMessage
	_ = json.Unmarshal(data, &root)
	return newProbeHealth(root)
}

// Exercise real observer updates while three instances are polled and routed.
// Run with -race: a copied slice alone is insufficient because statuses mutate.
func TestConcurrentObservationSnapshots(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(5 * time.Millisecond)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()
	for _, kind := range []string{"observatory", "burstObservatory"} {
		t.Run(kind, func(t *testing.T) {
			var ids []string
			assets := t.TempDir()
			defer func() {
				for _, id := range ids {
					stopTestProbe(t, id)
				}
			}()
			for i := 0; i < 3; i++ {
				observer := map[string]any{"subjectSelector": []string{"working"}, "probeURL": server.URL, "probeInterval": "10ms", "enableConcurrency": true}
				if kind == "burstObservatory" {
					observer = map[string]any{"subjectSelector": []string{"working"}, "pingConfig": map[string]any{"destination": server.URL, "connectivity": server.URL, "interval": "50ms", "sampling": 1, "timeout": "100ms"}}
				}
				id, _ := startTestProbe(t, map[string]any{
					"outbounds": []any{map[string]string{"tag": "working", "protocol": "freedom"}},
					"routing":   map[string]any{"rules": []any{map[string]string{"network": "tcp", "balancerTag": "auto"}}, "balancers": []any{map[string]any{"tag": "auto", "selector": []string{"working"}, "strategy": map[string]string{"type": "leastPing"}}}},
					kind:        observer,
				}, assets)
				ids = append(ids, id)
			}
			var wg sync.WaitGroup
			for _, id := range ids {
				wg.Go(func() {
					ready := false
					for i := 0; i < 100; i++ {
						r := invokeTest(t, "leadlink.probeObservation", map[string]any{"probeID": id})
						if r["success"] != true {
							t.Error("snapshot failed")
							return
						}
						ready = ready || r["data"].(map[string]any)["ready"] == true
						time.Sleep(5 * time.Millisecond)
					}
					if !ready {
						t.Error("observer never became ready")
					}
				})
			}
			wg.Wait()
		})
	}
}
func TestMeasuredReadinessKeepsStrategiesAndNoUnknownSuccess(t *testing.T) {
	for _, strategy := range []string{"leastPing", "leastLoad", "LEASTPING", "leastload"} {
		h := healthFixture(strategy, "", []string{"proxy-"})
		first := h.evaluate(nil)
		if !first.Supported || first.Ready || first.Exhausted || first.WaitBudgetMS != 10250 {
			t.Fatal(first)
		}
		ready := h.evaluate(map[string]bool{"proxy-b": true})
		if !ready.Ready || ready.Exhausted || ready.Revision == first.Revision {
			t.Fatal(ready)
		}
		if next := h.evaluate(map[string]bool{"proxy-b": true}); next.Revision != ready.Revision {
			t.Fatal("unchanged health advanced revision")
		}
		dead := h.evaluate(map[string]bool{"proxy-a": false, "proxy-b": false})
		if dead.Ready || !dead.Exhausted {
			t.Fatal(dead)
		}
	}
}
func TestFallbackWaitsForPrimaryStatusAndRetainsUnobservedBackup(t *testing.T) {
	for _, strategy := range []string{"random", "roundRobin", "RANDOM", "roundrobin", ""} {
		h := healthFixture(strategy, "backup", []string{"proxy-", "backup"})
		if r := h.evaluate(map[string]bool{"proxy-b": true, "backup": true}); r.Ready || r.Exhausted {
			t.Fatal("unknown primary prematurely ready", r)
		}
		if r := h.evaluate(map[string]bool{"proxy-a": false, "proxy-b": false, "backup": true}); !r.Ready {
			t.Fatal(r)
		}
		if r := h.evaluate(map[string]bool{"proxy-a": false, "proxy-b": false, "backup": false}); !r.Exhausted {
			t.Fatal(r)
		}
		h = healthFixture(strategy, "backup", []string{"proxy-"})
		if r := h.evaluate(map[string]bool{"proxy-a": false, "proxy-b": false}); !r.Ready {
			t.Fatal("provider does not watch fallback; request must test it", r)
		}
	}
}
func TestBlackholeAndUnobservedOrUnusedGroupsCannotGrantRecovery(t *testing.T) {
	h := healthFixture("leastPing", "blocked", []string{"proxy-", "blocked"})
	if r := h.evaluate(map[string]bool{"proxy-a": false, "proxy-b": false}); !r.Exhausted || r.Ready {
		t.Fatal(r)
	}
	for _, h := range []*probeHealth{healthFixture("random", "", []string{"proxy-"}), healthFixture("random", "backup", []string{"proxy-a"}), healthFixture("leastPing", "", nil)} {
		if h.evaluate(nil).Supported {
			t.Fatal("unmonitored strategy granted recovery")
		}
	}
}
func TestReadinessRequiresEveryRelevantGroupToSettle(t *testing.T) {
	h := healthFixture("leastPing", "", []string{"proxy-", "backup"})
	h.groups = append(h.groups, healthGroup{candidates: []string{"backup"}, measured: true})
	if h.evaluate(map[string]bool{"proxy-b": true}).Ready {
		t.Fatal("another group is still untested")
	}
	if !h.evaluate(map[string]bool{"proxy-b": true, "backup": false}).Ready {
		t.Fatal("settled failed group must not hide usable route in another group")
	}
}
func TestProbeObservationOwnershipAndCleanup(t *testing.T) {
	id, _ := startTestProbe(t, map[string]any{"outbounds": []any{map[string]string{"protocol": "freedom"}}}, t.TempDir())
	result := invokeTest(t, "leadlink.probeObservation", map[string]any{"probeID": id})
	if result["success"] != true || result["data"].(map[string]any)["supported"] != false {
		t.Fatal("unobserved profile state")
	}
	stopTestProbe(t, id)
	if invokeTest(t, "leadlink.probeObservation", map[string]any{"probeID": id})["success"] != false {
		t.Fatal("stopped probe is still readable")
	}
}
