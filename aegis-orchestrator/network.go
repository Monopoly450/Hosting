package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"sync"
	"time"
)

type DDoSRules struct {
	Enabled     bool   `json:"enabled"`
	MaxPPSPerIP int    `json:"max_pps_per_ip"`
	Action      string `json:"action"` // Drop, BlockIP
}

type NetworkStats struct {
	DPDKEnabled     bool           `json:"dpdk_enabled"`
	RingBufferDepth float64        `json:"ring_buffer_depth"` // %
	PPSIn           int            `json:"pps_in"`
	PPSClean        int            `json:"pps_clean"`
	PPSBlocked      int            `json:"pps_blocked"`
	BandwidthGbps   float64        `json:"bandwidth_gbps"`
	DDoSLogs        []DDoSLogEntry `json:"ddos_logs"`
	VSwitchTunnels  []VSwitchLink  `json:"vswitch_tunnels"`
}

type VSwitchLink struct {
	ContainerID string `json:"container_id"`
	Name        string `json:"container_name"`
	IP          string `json:"container_ip"`
	ExternalIP  string `json:"external_ip"`
	SHMSegment  string `json:"shm_segment"`
	LatencyMs   float64`json:"latency_ms"`
}

var (
	netMu        sync.Mutex
	netPPSIn     = 1200
	netPPSClean  = 1200
	netPPSBlock  = 0
	netBandwidth = 1.2
)

func handleNetwork(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	state.mu.RLock()
	defer state.mu.RUnlock()

	// Build virtual switch links dynamically based on running containers
	var tunnels []VSwitchLink
	ipCounter := 10
	for _, c := range state.Containers {
		if c.Status == "Running" {
			tunnels = append(tunnels, VSwitchLink{
				ContainerID: c.ID,
				Name:        c.Name,
				IP:          fmt.Sprintf("10.0.99.%d", ipCounter),
				ExternalIP:  fmt.Sprintf("185.190.140.%d", ipCounter),
				SHMSegment:  fmt.Sprintf("/dev/shm/aegis-net-%s", c.ID),
				LatencyMs:   0.02 + rand.Float64()*0.05, // super low latency because of shared memory & kernel bypass!
			})
			ipCounter++
		}
	}

	// DPDK ring buffer fullness fluctuates
	ringBuffer := 5.0 + rand.Float64()*8.0
	if state.DDoSActive {
		ringBuffer += 20.0 + rand.Float64()*15.0
	}

	stats := NetworkStats{
		DPDKEnabled:     true,
		RingBufferDepth: ringBuffer,
		PPSIn:           netPPSIn,
		PPSClean:        netPPSClean,
		PPSBlocked:      netPPSBlock,
		BandwidthGbps:   netBandwidth,
		DDoSLogs:        state.DDoSLogs,
		VSwitchTunnels:  tunnels,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

func handleDDoSConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method == "POST" {
		var req struct {
			Enabled      bool `json:"enabled"`
			MaxPPSPerIP  int  `json:"max_pps_per_ip"`
			TriggerDDoS  bool `json:"trigger_ddos"` // to force a ddos simulation
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		state.mu.Lock()
		state.DDoSRules.Enabled = req.Enabled
		state.DDoSRules.MaxPPSPerIP = req.MaxPPSPerIP
		if req.TriggerDDoS {
			state.DDoSActive = true
		} else if !req.Enabled {
			state.DDoSActive = false
		}
		state.mu.Unlock()

		saveState()
		broadcastUpdate("ddos_rules_updated", state.DDoSRules)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
		return
	}

	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
}

// Background thread simulating traffic flow and Anti-DDoS filtration
func ddosTrafficSimulator() {
	srcIPs := []string{"45.89.230.12", "198.51.100.44", "8.8.8.8", "77.88.55.66", "109.252.12.99"}
	attackTypes := []string{"SYN Flood", "UDP Reflection", "ICMP Flooding", "TCP RST Attack"}

	for {
		time.Sleep(1 * time.Second)

		state.mu.Lock()

		// Periodic random DDoS attack triggers (10% chance if not active)
		if !state.DDoSActive && rand.Intn(60) == 0 {
			state.DDoSActive = true
			entry := DDoSLogEntry{
				Time:   time.Now().Format("15:04:05"),
				Source: srcIPs[rand.Intn(len(srcIPs))],
				Type:   attackTypes[rand.Intn(len(attackTypes))],
				PPS:    50000 + rand.Intn(100000),
				Action: "Detected",
			}
			state.DDoSLogs = append([]DDoSLogEntry{entry}, state.DDoSLogs...)
			if len(state.DDoSLogs) > 30 {
				state.DDoSLogs = state.DDoSLogs[:30]
			}
		}

		// Calculate packet rates
		if state.DDoSActive {
			// DDoS active! Incoming spikes to massive levels
			attackPPS := 80000 + rand.Intn(40000)
			normalPPS := 1500 + rand.Intn(500)
			netPPSIn = attackPPS + normalPPS
			netBandwidth = 8.5 + rand.Float64()*4.0

			if state.DDoSRules.Enabled {
				// Anti-DDoS filter intercepts! Blocks attack traffic, allows clean
				netPPSBlock = attackPPS
				netPPSClean = normalPPS

				// Add a log entry for blocked packet slice
				if rand.Intn(3) == 0 {
					logEntry := DDoSLogEntry{
						Time:   time.Now().Format("15:04:05"),
						Source: srcIPs[rand.Intn(len(srcIPs))],
						Type:   attackTypes[rand.Intn(len(attackTypes))],
						PPS:    attackPPS,
						Action: "Blocked by DPDK eBPF Engine",
					}
					state.DDoSLogs = append([]DDoSLogEntry{logEntry}, state.DDoSLogs...)
					if len(state.DDoSLogs) > 30 {
						state.DDoSLogs = state.DDoSLogs[:30]
					}
				}

				// De-escalate DDoS after a while
				if rand.Intn(15) == 0 {
					state.DDoSActive = false
				}
			} else {
				// Anti-DDoS is disabled! All traffic goes to CPU, causing load
				netPPSBlock = 0
				netPPSClean = netPPSIn // CPU is flooded!
				
				// De-escalate
				if rand.Intn(10) == 0 {
					state.DDoSActive = false
				}
			}
		} else {
			// Normal clean traffic
			netPPSIn = 1000 + rand.Intn(500)
			netPPSClean = netPPSIn
			netPPSBlock = 0
			netBandwidth = 0.5 + rand.Float64()*0.8
		}

		state.mu.Unlock()

		// Stream network stats updates
		var tunnels []VSwitchLink
		ipCounter := 10
		state.mu.RLock()
		for _, c := range state.Containers {
			if c.Status == "Running" {
				tunnels = append(tunnels, VSwitchLink{
					ContainerID: c.ID,
					Name:        c.Name,
					IP:          fmt.Sprintf("10.0.99.%d", ipCounter),
					ExternalIP:  fmt.Sprintf("185.190.140.%d", ipCounter),
					SHMSegment:  fmt.Sprintf("/dev/shm/aegis-net-%s", c.ID),
					LatencyMs:   0.02 + rand.Float64()*0.05,
				})
				ipCounter++
			}
		}

		ringBuffer := 5.0 + rand.Float64()*8.0
		if state.DDoSActive {
			ringBuffer += 20.0 + rand.Float64()*15.0
		}
		ddosActive := state.DDoSActive
		state.mu.RUnlock()

		netMsg := map[string]interface{}{
			"type": "network_update",
			"data": map[string]interface{}{
				"dpdk_enabled":      true,
				"ring_buffer_depth": ringBuffer,
				"pps_in":            netPPSIn,
				"pps_clean":         netPPSClean,
				"pps_blocked":        netPPSBlock,
				"bandwidth_gbps":    netBandwidth,
				"ddos_active":       ddosActive,
				"vswitch_tunnels":   tunnels,
			},
		}
		jsonBytes, err := json.Marshal(netMsg)
		if err == nil {
			broker.messages <- string(jsonBytes)
		}
	}
}
