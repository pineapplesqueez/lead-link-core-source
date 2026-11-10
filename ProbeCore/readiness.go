package main

import (
	"context"
	"encoding/json"
	"sort"
	"strings"
	"time"

	"github.com/xtls/xray-core/app/observatory"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/features/extension"
)

// Readiness is only a signal to retry the original request. It never chooses an
// outbound, edits a rule, changes an observer or treats health as HTTP success.
type probeObservation struct {
	Supported    bool   `json:"supported"`
	Ready        bool   `json:"ready"`
	Exhausted    bool   `json:"exhausted"`
	Revision     uint64 `json:"revision"`
	WaitBudgetMS int64  `json:"waitBudgetMS"`
}
type healthGroup struct {
	candidates []string
	fallback   string
	measured   bool
}
type probeHealth struct {
	groups    []healthGroup
	watched   map[string]bool
	protocols map[string]string
	tags      []string
	budget    time.Duration
	signature string
	revision  uint64
}

func matches(tag string, selectors []string) bool {
	for _, prefix := range selectors {
		if strings.HasPrefix(tag, prefix) {
			return true
		}
	}
	return false
}
func newProbeHealth(root map[string]json.RawMessage) *probeHealth {
	h := &probeHealth{watched: map[string]bool{}, protocols: map[string]string{}, budget: 10 * time.Second}
	var outbounds []struct{ Tag, Protocol string }
	var routing struct {
		Rules     []struct{ BalancerTag string }
		Balancers []struct {
			Tag, FallbackTag string
			Selector         []string
			Strategy         struct{ Type string }
		}
	}
	_ = json.Unmarshal(root["outbounds"], &outbounds)
	_ = json.Unmarshal(root["routing"], &routing)
	var subjects []string
	for _, name := range []string{"observatory", "burstObservatory"} {
		var observer struct {
			SubjectSelector []string
			PingConfig      struct{ Timeout string }
		}
		if json.Unmarshal(root[name], &observer) == nil {
			subjects = append(subjects, observer.SubjectSelector...)
			if name == "burstObservatory" {
				h.budget = 5 * time.Second
				if value, err := time.ParseDuration(observer.PingConfig.Timeout); err == nil && value > 0 {
					h.budget = value
				}
			}
		}
	}
	if h.budget > 10*time.Second {
		h.budget = 10 * time.Second
	}
	// Burst first probes the outbound, then checks direct connectivity before
	// publishing a failure. Both requests can consume their timeout. Keep the
	// total observation bound at 10s without changing either provider setting.
	if _, burst := root["burstObservatory"]; burst {
		h.budget = min(2*h.budget, 10*time.Second)
	}
	h.budget += 250 * time.Millisecond // allow the observer to publish its timeout
	used := map[string]bool{}
	for _, rule := range routing.Rules {
		used[rule.BalancerTag] = true
	}
	for _, o := range outbounds {
		h.protocols[o.Tag] = o.Protocol
		if matches(o.Tag, subjects) {
			h.watched[o.Tag] = true
		}
	}
	relevant := map[string]bool{}
	for _, b := range routing.Balancers {
		if !used[b.Tag] {
			continue
		}
		// Upstream accepts strategy names case-insensitively.
		strategy := strings.ToLower(b.Strategy.Type)
		measured := strategy == "leastping" || strategy == "leastload"
		if !measured && !((strategy == "random" || strategy == "roundrobin" || strategy == "") && b.FallbackTag != "") {
			continue
		}
		g := healthGroup{fallback: b.FallbackTag, measured: measured}
		watchedCount := 0
		for _, o := range outbounds {
			if matches(o.Tag, b.Selector) {
				g.candidates = append(g.candidates, o.Tag)
				if h.watched[o.Tag] {
					watchedCount++
				}
			}
		}
		// Random/roundRobin permanently consider unobserved candidates alive.
		// Do not invent readiness/failover for a provider that does not watch them.
		if watchedCount == 0 || (!measured && watchedCount != len(g.candidates)) {
			continue
		}
		h.groups = append(h.groups, g)
		for _, tag := range g.candidates {
			if h.watched[tag] {
				relevant[tag] = true
			}
		}
		if h.watched[g.fallback] {
			relevant[g.fallback] = true
		}
	}
	for tag := range relevant {
		h.tags = append(h.tags, tag)
	}
	sort.Strings(h.tags)
	return h
}
func (h *probeHealth) evaluate(statuses map[string]bool) probeObservation {
	r := probeObservation{Supported: len(h.groups) > 0, WaitBudgetMS: h.budget.Milliseconds()}
	if !r.Supported {
		return r
	}
	signature := make([]byte, 0, len(h.tags))
	for _, tag := range h.tags {
		v, ok := statuses[tag]
		switch {
		case !ok:
			signature = append(signature, '?')
		case v:
			signature = append(signature, '+')
		default:
			signature = append(signature, '-')
		}
	}
	if string(signature) != h.signature || h.revision == 0 {
		h.signature = string(signature)
		h.revision++
	}
	r.Revision = h.revision
	allSettled, anyUsable := true, false
	for _, g := range h.groups {
		alive, pending := 0, 0
		for _, tag := range g.candidates {
			if !h.watched[tag] {
				continue
			}
			v, ok := statuses[tag]
			if !ok {
				pending++
			} else if v {
				alive++
			}
		}
		if alive > 0 && (g.measured || pending == 0) {
			anyUsable = true
			continue
		}
		if pending > 0 {
			allSettled = false
			continue
		}
		if g.fallback != "" && h.protocols[g.fallback] != "blackhole" {
			if !h.watched[g.fallback] {
				anyUsable = true
				continue
			}
			v, ok := statuses[g.fallback]
			if !ok {
				allSettled = false
			} else if v {
				anyUsable = true
			}
		}
	}
	r.Ready = allSettled && anyUsable
	r.Exhausted = allSettled && !anyUsable
	return r
}
func (h *probeHealth) observation(instance *core.Instance) (probeObservation, error) {
	if len(h.groups) == 0 {
		return h.evaluate(nil), nil
	}
	observer, ok := instance.GetFeature(extension.ObservatoryType()).(extension.Observatory)
	if !ok {
		return probeObservation{}, nil
	}
	raw, err := observer.GetObservation(context.Background())
	if err != nil {
		return probeObservation{}, err
	}
	report, ok := raw.(*observatory.ObservationResult)
	if !ok {
		return probeObservation{}, nil
	}
	statuses := map[string]bool{}
	for _, status := range report.Status {
		if status != nil {
			statuses[status.OutboundTag] = status.Alive
		}
	}
	return h.evaluate(statuses), nil
}
