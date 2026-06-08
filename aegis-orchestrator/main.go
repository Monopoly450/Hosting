package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Global system state
type SystemState struct {
	mu           sync.RWMutex
	Containers   []*Container    `json:"containers"`
	S3Nodes      []*S3Node       `json:"s3_nodes"`
	DDoSRules    *DDoSRules      `json:"ddos_rules"`
	DDoSActive   bool            `json:"ddos_active"`
	Balance      float64         `json:"balance"` // in USD
	BillingRate  float64         `json:"billing_rate"` // USD/sec
	Transactions []Transaction   `json:"transactions"`
	DDoSLogs     []DDoSLogEntry  `json:"ddos_logs"`
}

type Transaction struct {
	Time   string  `json:"time"`
	Amount float64 `json:"amount"`
	Desc   string  `json:"desc"`
}

type DDoSLogEntry struct {
	Time   string `json:"time"`
	Source string `json:"source"`
	Type   string `json:"type"`
	PPS    int    `json:"pps"`
	Action string `json:"action"`
}

var state = &SystemState{
	Containers: []*Container{
		{
			ID:         "c-01",
			Name:       "aegis-core-db",
			Status:     "Running",
			CPUCores:   2,
			RAMLimitGB: 4,
			CPUPinning: []int{0, 1},
			Namespaces: []string{"mnt", "uts", "ipc", "pid", "net"},
			CgroupPath: "/sys/fs/cgroup/aegis/c-01",
		},
		{
			ID:         "c-02",
			Name:       "aegis-frontend-cache",
			Status:     "Running",
			CPUCores:   1,
			RAMLimitGB: 2,
			CPUPinning: []int{2},
			Namespaces: []string{"mnt", "uts", "ipc", "pid", "net"},
			CgroupPath: "/sys/fs/cgroup/aegis/c-02",
		},
	},
	S3Nodes: []*S3Node{
		{ID: 1, Name: "S3-Storage-Node-1", Status: "Online", Path: "/app/data/s3/node_1", ActiveParts: 0},
		{ID: 2, Name: "S3-Storage-Node-2", Status: "Online", Path: "/app/data/s3/node_2", ActiveParts: 0},
		{ID: 3, Name: "S3-Storage-Node-3", Status: "Online", Path: "/app/data/s3/node_3", ActiveParts: 0},
		{ID: 4, Name: "S3-Storage-Node-4", Status: "Online", Path: "/app/data/s3/node_4", ActiveParts: 0},
		{ID: 5, Name: "S3-Storage-Node-5", Status: "Online", Path: "/app/data/s3/node_5", ActiveParts: 0},
		{ID: 6, Name: "S3-Storage-Node-6", Status: "Online", Path: "/app/data/s3/node_6", ActiveParts: 0},
	},
	DDoSRules: &DDoSRules{
		Enabled:     true,
		MaxPPSPerIP: 1000,
		Action:      "Drop",
	},
	DDoSActive: false,
	Balance:    100.0,
	BillingRate: 0.00015,
	Transactions: []Transaction{
		{Time: time.Now().Format("15:04:05"), Amount: 100.0, Desc: "Начальное пополнение баланса"},
	},
	DDoSLogs: []DDoSLogEntry{},
}

const stateFile = "/app/data/aegis_state.json"

func loadState() {
	state.mu.Lock()
	defer state.mu.Unlock()

	data, err := os.ReadFile(stateFile)
	if err == nil {
		var loaded SystemState
		if err := json.Unmarshal(data, &loaded); err == nil {
			state.Containers = loaded.Containers
			state.S3Nodes = loaded.S3Nodes
			state.DDoSRules = loaded.DDoSRules
			state.DDoSActive = loaded.DDoSActive
			state.Balance = loaded.Balance
			state.BillingRate = loaded.BillingRate
			state.Transactions = loaded.Transactions
			state.DDoSLogs = loaded.DDoSLogs
		}
	}
}

func saveState() {
	state.mu.RLock()
	defer state.mu.RUnlock()

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return
	}
	os.MkdirAll(filepath.Dir(stateFile), 0755)
	_ = os.WriteFile(stateFile, data, 0644)
}

// SSE Clients Broker
type Broker struct {
	clients    map[chan string]bool
	newClients chan chan string
	defClients chan chan string
	messages   chan string
}

var broker = &Broker{
	clients:    make(map[chan string]bool),
	newClients: make(chan chan string),
	defClients: make(chan chan string),
	messages:   make(chan string),
}

func (b *Broker) Start() {
	for {
		select {
		case s := <-b.newClients:
			b.clients[s] = true
		case s := <-b.defClients:
			delete(b.clients, s)
			close(s)
		case msg := <-b.messages:
			for clientChan := range b.clients {
				select {
				case clientChan <- msg:
				default:
				}
			}
		}
	}
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func main() {
	loadState()
	go broker.Start()

	// Create directories for S3 nodes
	for _, n := range state.S3Nodes {
		os.MkdirAll(n.Path, 0755)
	}

	initMetricsTSDB()
	go billingLoop()
	go ddosTrafficSimulator()

	mux := http.NewServeMux()

	// SSE stream
	mux.HandleFunc("/api/aegis/stream", handleStream)

	// Compute endpoints
	mux.HandleFunc("/api/aegis/containers", handleContainers)
	mux.HandleFunc("/api/aegis/containers/action", handleContainerAction)

	// Network endpoints
	mux.HandleFunc("/api/aegis/network", handleNetwork)
	mux.HandleFunc("/api/aegis/network/ddos", handleDDoSConfig)

	// Storage endpoints
	mux.HandleFunc("/api/aegis/storage", handleStorage)
	mux.HandleFunc("/api/aegis/storage/benchmark", handleStorageBenchmark)
	mux.HandleFunc("/api/aegis/storage/upload", handleStorageUpload)
	mux.HandleFunc("/api/aegis/storage/node/toggle", handleStorageNodeToggle)
	mux.HandleFunc("/api/aegis/storage/recover", handleStorageRecover)

	// Metrics and Billing
	mux.HandleFunc("/api/aegis/metrics", handleMetrics)
	mux.HandleFunc("/api/aegis/billing", handleBilling)

	// AWS Console Endpoints
	mux.HandleFunc("/api/aegis/aws", handleAWS)
	mux.HandleFunc("/api/aegis/aws/security-groups", handleAWSSecurityGroups)
	mux.HandleFunc("/api/aegis/aws/s3/buckets", handleAWSS3Buckets)
	mux.HandleFunc("/api/aegis/aws/iam", handleAWSIAM)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8001"
	}

	log.Printf("Aegis Cloud Engine Orchestrator starting on port %s...", port)
	log.Fatal(http.ListenAndServe(":"+port, corsMiddleware(mux)))
}

func handleStream(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	clientChan := make(chan string, 100)
	broker.newClients <- clientChan

	defer func() {
		broker.defClients <- clientChan
	}()

	notifyChan := r.Context().Done()

	initMsg := map[string]interface{}{
		"type": "init",
		"data": map[string]interface{}{
			"containers":  state.Containers,
			"s3_nodes":    state.S3Nodes,
			"ddos_rules":  state.DDoSRules,
			"ddos_active": state.DDoSActive,
			"balance":     state.Balance,
			"billing_rate": state.BillingRate,
		},
	}
	initJSON, _ := json.Marshal(initMsg)
	fmt.Fprintf(w, "data: %s\n\n", string(initJSON))
	w.(http.Flusher).Flush()

	for {
		select {
		case <-notifyChan:
			return
		case msg := <-clientChan:
			fmt.Fprintf(w, "data: %s\n\n", msg)
			w.(http.Flusher).Flush()
		}
	}
}

// AWS API Handlers

func handleAWS(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	awsState.mu.RLock()
	defer awsState.mu.RUnlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(awsState)
}

func handleAWSSecurityGroups(w http.ResponseWriter, r *http.Request) {
	if r.Method == "POST" {
		var req struct {
			Action      string              `json:"action"` // create, update_rules, bind
			ID          string              `json:"id"`
			Name        string              `json:"name"`
			Description string              `json:"description"`
			Rules       []SecurityGroupRule `json:"rules"`
			Instance    string              `json:"instance"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		awsState.mu.Lock()
		defer awsState.mu.Unlock()

		switch req.Action {
		case "create":
			id := fmt.Sprintf("sg-%09d", rand.Intn(1000000000))
			sg := &SecurityGroup{
				ID:          id,
				Name:        req.Name,
				Description: req.Description,
				Rules: []SecurityGroupRule{
					{Type: "Outbound", Protocol: "all", PortRange: "all", Source: "0.0.0.0/0"},
				},
				BoundInstances: []string{},
			}
			awsState.SecurityGroups = append(awsState.SecurityGroups, sg)
		case "update_rules":
			for _, sg := range awsState.SecurityGroups {
				if sg.ID == req.ID {
					sg.Rules = req.Rules
					for _, containerID := range sg.BoundInstances {
						ApplySecurityGroupRules(containerID, sg.Rules)
					}
					break
				}
			}
		case "bind":
			for _, sg := range awsState.SecurityGroups {
				if sg.ID == req.ID {
					found := false
					for _, b := range sg.BoundInstances {
						if b == req.Instance {
							found = true
							break
						}
					}
					if !found {
						sg.BoundInstances = append(sg.BoundInstances, req.Instance)
						ApplySecurityGroupRules(req.Instance, sg.Rules)
					}
					break
				}
			}
		}

		saveAWSState()
		broadcastUpdate("aws_update", nil)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
		return
	}
	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func handleAWSS3Buckets(w http.ResponseWriter, r *http.Request) {
	if r.Method == "POST" {
		var req struct {
			Action       string `json:"action"` // create, delete, upload, toggle_policy
			Name         string `json:"name"`
			AccessPolicy string `json:"access_policy"`
			Key          string `json:"key"`
			Size         int64  `json:"size"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		awsState.mu.Lock()
		defer awsState.mu.Unlock()

		switch req.Action {
		case "create":
			for _, b := range awsState.S3Buckets {
				if b.Name == req.Name {
					http.Error(w, "Бакет с таким именем уже существует", http.StatusConflict)
					return
				}
			}
			bucket := &S3Bucket{
				Name:         req.Name,
				Region:       "us-east-1",
				AccessPolicy: "Private",
				Objects:      []S3BucketObject{},
			}
			awsState.S3Buckets = append(awsState.S3Buckets, bucket)
		case "delete":
			for i, b := range awsState.S3Buckets {
				if b.Name == req.Name {
					awsState.S3Buckets = append(awsState.S3Buckets[:i], awsState.S3Buckets[i+1:]...)
					break
				}
			}
		case "toggle_policy":
			for _, b := range awsState.S3Buckets {
				if b.Name == req.Name {
					if b.AccessPolicy == "Private" {
						b.AccessPolicy = "Public-Read"
					} else {
						b.AccessPolicy = "Private"
					}
					break
				}
			}
		case "upload":
			for _, b := range awsState.S3Buckets {
				if b.Name == req.Name {
					obj := S3BucketObject{
						Key:        req.Key,
						Size:       req.Size,
						LastUpdate: time.Now().Format("2006-01-02 15:04:05"),
					}
					b.Objects = append(b.Objects, obj)
					break
				}
			}
		}

		saveAWSState()
		broadcastUpdate("aws_update", nil)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
		return
	}
	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func handleAWSIAM(w http.ResponseWriter, r *http.Request) {
	if r.Method == "POST" {
		var req struct {
			Action   string `json:"action"` // create, update_policy, delete
			Username string `json:"username"`
			Policy   string `json:"policy"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		awsState.mu.Lock()
		defer awsState.mu.Unlock()

		switch req.Action {
		case "create":
			var p IAMPolicy
			if err := json.Unmarshal([]byte(req.Policy), &p); err != nil {
				http.Error(w, "Неверный синтаксис JSON политики: "+err.Error(), http.StatusBadRequest)
				return
			}
			user := &IAMUser{
				Username: req.Username,
				JoinedAt: time.Now().Format("2006-01-02 15:04:05"),
				Policy:   req.Policy,
			}
			awsState.IAMUsers = append(awsState.IAMUsers, user)
		case "update_policy":
			var p IAMPolicy
			if err := json.Unmarshal([]byte(req.Policy), &p); err != nil {
				http.Error(w, "Неверный синтаксис JSON политики: "+err.Error(), http.StatusBadRequest)
				return
			}
			for _, u := range awsState.IAMUsers {
				if u.Username == req.Username {
					u.Policy = req.Policy
					break
				}
			}
		case "delete":
			for i, u := range awsState.IAMUsers {
				if u.Username == req.Username {
					awsState.IAMUsers = append(awsState.IAMUsers[:i], awsState.IAMUsers[i+1:]...)
					break
				}
			}
		}

		saveAWSState()
		broadcastUpdate("aws_update", nil)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
		return
	}
	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
}
