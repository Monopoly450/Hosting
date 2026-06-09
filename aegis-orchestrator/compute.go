package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
)

type Container struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Status     string   `json:"status"` // Running, Stopped
	CPUCores   int      `json:"cpu_cores"`
	RAMLimitGB int      `json:"ram_limit_gb"`
	CPUPinning []int    `json:"cpu_pinning"`
	Namespaces []string `json:"namespaces"`
	CgroupPath string   `json:"cgroup_path"`
	PID        int      `json:"pid,omitempty"`
}

type CreateContainerInput struct {
	Name       string `json:"name"`
	CPUCores   int    `json:"cpu_cores"`
	RAMLimitGB int    `json:"ram_limit_gb"`
	CPUPinning []int  `json:"cpu_pinning"`
}

var computeMu sync.Mutex

func handleContainers(w http.ResponseWriter, r *http.Request) {
	if r.Method == "GET" {
		state.mu.RLock()
		defer state.mu.RUnlock()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(state.Containers)
		return
	}

	if r.Method == "POST" {
		var input CreateContainerInput
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		if input.Name == "" || input.CPUCores <= 0 || input.RAMLimitGB <= 0 {
			http.Error(w, "Неверные параметры контейнера", http.StatusBadRequest)
			return
		}

		computeMu.Lock()
		defer computeMu.Unlock()

		state.mu.Lock()
		// CPU Pinning check - No Overselling
		pinnedCores := make(map[int]string)
		for _, c := range state.Containers {
			if c.Status == "Running" {
				for _, core := range c.CPUPinning {
					pinnedCores[core] = c.Name
				}
			}
		}

		for _, requestedCore := range input.CPUPinning {
			if occupier, exists := pinnedCores[requestedCore]; exists {
				state.mu.Unlock()
				http.Error(w, fmt.Sprintf("Конфликт CPU Pinning: Ядро %d уже жестко закреплено за контейнером '%s'", requestedCore, occupier), http.StatusConflict)
				return
			}
		}

		id := fmt.Sprintf("c-%02d", len(state.Containers)+1)
		cgroupPath := fmt.Sprintf("/sys/fs/cgroup/aegis/%s", id)

		newContainer := &Container{
			ID:         id,
			Name:       input.Name,
			Status:     "Running",
			CPUCores:   input.CPUCores,
			RAMLimitGB: input.RAMLimitGB,
			CPUPinning: input.CPUPinning,
			Namespaces: []string{"mnt", "uts", "ipc", "pid", "net"},
			CgroupPath: cgroupPath,
		}

		state.Containers = append(state.Containers, newContainer)
		recalculateBillingRate()
		state.mu.Unlock()

		// Execute low level container setups
		setupLowLevelContainer(newContainer)

		// Сохранение в БД
		_, _ = dbPool.Exec(context.Background(), "INSERT INTO containers (id, name, status, cpu_cores, ram_limit_gb, cpu_pinning, namespaces, cgroup_path, pid) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
			newContainer.ID, newContainer.Name, newContainer.Status, newContainer.CPUCores, newContainer.RAMLimitGB, toJSONB(newContainer.CPUPinning), toJSONB(newContainer.Namespaces), newContainer.CgroupPath, newContainer.PID)

		saveState()
		broadcastUpdate("container_created", newContainer)

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(newContainer)
		return
	}

	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func handleContainerAction(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		ID     string `json:"id"`
		Action string `json:"action"` // start, stop, delete
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	state.mu.Lock()
	defer state.mu.Unlock()

	var found *Container
	var foundIdx = -1
	for idx, c := range state.Containers {
		if c.ID == req.ID {
			found = c
			foundIdx = idx
			break
		}
	}

	if found == nil {
		http.Error(w, "Контейнер не найден", http.StatusNotFound)
		return
	}

	switch req.Action {
	case "start":
		pinnedCores := make(map[int]string)
		for _, c := range state.Containers {
			if c.Status == "Running" && c.ID != found.ID {
				for _, core := range c.CPUPinning {
					pinnedCores[core] = c.Name
				}
			}
		}
		for _, requestedCore := range found.CPUPinning {
			if occupier, exists := pinnedCores[requestedCore]; exists {
				http.Error(w, fmt.Sprintf("Конфликт CPU Pinning: Ядро %d занято контейнером '%s'", requestedCore, occupier), http.StatusConflict)
				return
			}
		}

		found.Status = "Running"
		setupLowLevelContainer(found)
		_, _ = dbPool.Exec(context.Background(), "UPDATE containers SET status='Running', pid=$1 WHERE id=$2", found.PID, found.ID)
	case "stop":
		found.Status = "Stopped"
		teardownLowLevelContainer(found)
		_, _ = dbPool.Exec(context.Background(), "UPDATE containers SET status='Stopped', pid=0 WHERE id=$2", found.ID)
	case "delete":
		teardownLowLevelContainer(found)
		state.Containers = append(state.Containers[:foundIdx], state.Containers[foundIdx+1:]...)
		_, _ = dbPool.Exec(context.Background(), "DELETE FROM containers WHERE id=$1", found.ID)
	default:
		http.Error(w, "Неверное действие", http.StatusBadRequest)
		return
	}

	recalculateBillingRate()
	go saveState()
	go broadcastUpdate("container_action", found)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func recalculateBillingRate() {
	var total float64 = 0.0
	for _, c := range state.Containers {
		if c.Status == "Running" {
			total += float64(c.CPUCores)*0.00005 + float64(c.RAMLimitGB)*0.00002
		}
	}
	state.BillingRate = total
}

func setupLowLevelContainer(c *Container) {
	fmt.Printf("[Aegis-Compute] Настройка контейнера %s (ID: %s)\n", c.Name, c.ID)

	if runtime.GOOS != "linux" {
		fmt.Printf("[Aegis-Compute] [СИМУЛЯЦИЯ] Созданы изолированные namespaces (%v) и установлены лимиты cgroups v2 для RAM (%d GB)\n", c.Namespaces, c.RAMLimitGB)
		return
	}

	// 1. Enable controllers in parent cgroups v2
	_ = os.WriteFile("/sys/fs/cgroup/cgroup.subtree_control", []byte("+cpuset +memory"), 0644)
	
	aegisRoot := "/sys/fs/cgroup/aegis"
	_ = os.MkdirAll(aegisRoot, 0755)
	_ = os.WriteFile(filepath.Join(aegisRoot, "cgroup.subtree_control"), []byte("+cpuset +memory"), 0644)

	// Create cgroups v2 directory for container
	err := os.MkdirAll(c.CgroupPath, 0755)
	if err != nil {
		fmt.Printf("[Aegis-Compute] Ошибка создания cgroup: %v\n", err)
		return
	}

	// Set RAM limits in cgroups v2 (memory.max)
	memLimitBytes := int64(c.RAMLimitGB) * 1024 * 1024 * 1024
	_ = os.WriteFile(filepath.Join(c.CgroupPath, "memory.max"), []byte(fmt.Sprintf("%d", memLimitBytes)), 0644)

	// Set CPU cpuset pinning (cpuset.cpus)
	var cpusStr string
	for i, core := range c.CPUPinning {
		if i > 0 {
			cpusStr += ","
		}
		cpusStr += fmt.Sprintf("%d", core)
	}
	_ = os.WriteFile(filepath.Join(c.CgroupPath, "cpuset.cpus"), []byte(cpusStr), 0644)

	// 2. Spawn isolated process using Linux namespaces (CLONE_NEWPID, CLONE_NEWNET, CLONE_NEWNS, CLONE_NEWUTS, CLONE_NEWIPC, CLONE_NEWUSER)
	// We run a sleep loop shell inside namespaces
	cmd := exec.Command("/bin/sh", "-c", "while true; do sleep 15; done")
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Cloneflags: syscall.CLONE_NEWPID | syscall.CLONE_NEWNS | syscall.CLONE_NEWNET | syscall.CLONE_NEWUTS | syscall.CLONE_NEWIPC | syscall.CLONE_NEWUSER,
	}

	err = cmd.Start()
	if err != nil {
		fmt.Printf("[Aegis-Compute] Предупреждение: не удалось запустить с CLONE_NEWUSER (%v). Пробуем запустить без изоляции пользовательского неймспейса...\n", err)
		cmd = exec.Command("/bin/sh", "-c", "while true; do sleep 15; done")
		cmd.SysProcAttr = &syscall.SysProcAttr{
			Cloneflags: syscall.CLONE_NEWPID | syscall.CLONE_NEWNS | syscall.CLONE_NEWNET | syscall.CLONE_NEWUTS | syscall.CLONE_NEWIPC,
		}
		err = cmd.Start()
	}

	if err != nil {
		fmt.Printf("[Aegis-Compute] Ошибка запуска процесса в namespace: %v\n", err)
		return
	}

	c.PID = cmd.Process.Pid
	_, _ = dbPool.Exec(context.Background(), "UPDATE containers SET pid=$1 WHERE id=$2", c.PID, c.ID)

	// Add PID of namespace process to cgroups v2 to throttle it
	pidPath := filepath.Join(c.CgroupPath, "cgroup.procs")
	_ = os.WriteFile(pidPath, []byte(fmt.Sprintf("%d", c.PID)), 0644)

	fmt.Printf("[Aegis-Compute] Запущен процесс PID %d в namespaces с лимитами cgroups v2 и CPU Pinning к ядрам %s\n", c.PID, cpusStr)
}

func teardownLowLevelContainer(c *Container) {
	fmt.Printf("[Aegis-Compute] Остановка контейнера %s\n", c.Name)
	if c.PID > 0 {
		proc, err := os.FindProcess(c.PID)
		if err == nil {
			_ = proc.Kill()
		}
		c.PID = 0
	}
	if runtime.GOOS == "linux" {
		// Clean up cgroups directory
		_ = os.Remove(c.CgroupPath)
	}
}

func broadcastUpdate(evtType string, data interface{}) {
	msg := map[string]interface{}{
		"type": evtType,
		"data": data,
		"metrics": map[string]interface{}{
			"balance":      state.Balance,
			"billing_rate": state.BillingRate,
			"containers":   state.Containers,
			"s3_nodes":     state.S3Nodes,
			"ddos_active":  state.DDoSActive,
		},
	}
	jsonBytes, err := json.Marshal(msg)
	if err == nil {
		broker.messages <- string(jsonBytes)
	}
}
