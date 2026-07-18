package client

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newTestServer(t *testing.T, handler http.HandlerFunc) (*Client, func()) {
	t.Helper()
	srv := httptest.NewServer(handler)
	return New(srv.URL, "aeg_testtoken"), srv.Close
}

func TestCreateVM(t *testing.T) {
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/api/vms" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer aeg_testtoken" {
			t.Errorf("missing/incorrect auth header: %q", got)
		}
		var body VMCreate
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.Name != "web-1" || body.CPUCores != 2 {
			t.Errorf("unexpected body: %+v", body)
		}
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(VMCreateResponse{Status: "creating", Name: "web-1", TaskID: 42})
	})
	defer closeFn()

	out, err := c.CreateVM(context.Background(), VMCreate{Name: "web-1", OSType: "ubuntu", CPUCores: 2, MemoryGB: 2, DiskGB: 20})
	if err != nil {
		t.Fatalf("CreateVM error: %v", err)
	}
	if out.TaskID != 42 {
		t.Errorf("expected task_id 42, got %d", out.TaskID)
	}
}

func TestGetVM(t *testing.T) {
	port := int64(22042)
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/vms/web-1" {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(VM{
			Name: "web-1", Status: "Running", OSType: "ubuntu",
			CPUCores: 2, Memory: "2Gi", IPs: []string{"192.168.100.11"}, SSHPort: &port,
		})
	})
	defer closeFn()

	vm, err := c.GetVM(context.Background(), "web-1")
	if err != nil {
		t.Fatalf("GetVM error: %v", err)
	}
	if vm.PrimaryIP() != "192.168.100.11" {
		t.Errorf("expected primary ip, got %q", vm.PrimaryIP())
	}
	if vm.SSHPort == nil || *vm.SSHPort != 22042 {
		t.Errorf("expected ssh port 22042, got %v", vm.SSHPort)
	}
}

func TestGetVMNotFound(t *testing.T) {
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	defer closeFn()

	_, err := c.GetVM(context.Background(), "ghost")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestDeleteVMIdempotent(t *testing.T) {
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound) // уже удалена
	})
	defer closeFn()

	if err := c.DeleteVM(context.Background(), "ghost"); err != nil {
		t.Fatalf("DeleteVM should be idempotent on 404, got %v", err)
	}
}

func TestErrorDetailParsed(t *testing.T) {
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]string{"detail": "квота превышена"})
	})
	defer closeFn()

	_, err := c.CreateVM(context.Background(), VMCreate{Name: "x"})
	if err == nil || !contains(err.Error(), "квота превышена") {
		t.Fatalf("expected detail in error, got %v", err)
	}
}

func TestGetDatabaseFiltersByID(t *testing.T) {
	c, closeFn := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/databases" {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode([]Database{
			{ID: 1, DBName: "a", Engine: "postgresql"},
			{ID: 7, DBName: "b", Engine: "mysql", DBUser: "u_x", DBPassword: "secret"},
		})
	})
	defer closeFn()

	db, err := c.GetDatabase(context.Background(), 7)
	if err != nil {
		t.Fatalf("GetDatabase error: %v", err)
	}
	if db.DBName != "b" || db.DBPassword != "secret" {
		t.Errorf("wrong db returned: %+v", db)
	}

	if _, err := c.GetDatabase(context.Background(), 999); !errors.Is(err, ErrNotFound) {
		t.Errorf("expected ErrNotFound for missing id, got %v", err)
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
