// Package client — тонкая обёртка над REST API панели ByteBurners (Aegis).
// Аутентификация выполняется персональным API-токеном (aeg_...) через
// заголовок Authorization: Bearer.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ErrNotFound возвращается, когда ресурс отсутствует (HTTP 404).
var ErrNotFound = errors.New("resource not found")

// Client — HTTP-клиент к панели Aegis.
type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

// New создаёт клиент. baseURL — адрес панели (например http://SERVER:8000),
// token — персональный API-токен (aeg_...).
func New(baseURL, token string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Token:   token,
		HTTP:    &http.Client{Timeout: 60 * time.Second},
	}
}

// apiError — тело ошибки FastAPI ({"detail": "..."}).
type apiError struct {
	Detail json.RawMessage `json:"detail"`
}

func (c *Client) do(ctx context.Context, method, path string, body, out interface{}) error {
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal request body: %w", err)
		}
		reader = bytes.NewReader(raw)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+"/api"+path, reader)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.Token)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("call %s %s: %w", method, path, err)
	}
	defer resp.Body.Close()

	data, _ := io.ReadAll(resp.Body)

	if resp.StatusCode == http.StatusNotFound {
		return ErrNotFound
	}
	if resp.StatusCode >= 400 {
		detail := strings.TrimSpace(string(data))
		var ae apiError
		if json.Unmarshal(data, &ae) == nil && len(ae.Detail) > 0 {
			// detail может быть строкой или массивом (ошибки валидации)
			var s string
			if json.Unmarshal(ae.Detail, &s) == nil {
				detail = s
			} else {
				detail = string(ae.Detail)
			}
		}
		return fmt.Errorf("API %d: %s", resp.StatusCode, detail)
	}

	if out != nil && len(data) > 0 {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}

// ---------------------------- Виртуальные машины ----------------------------

// VMCreate — тело запроса на создание ВМ.
type VMCreate struct {
	Name        string `json:"name"`
	OSType      string `json:"os_type"`
	CPUCores    int64  `json:"cpu_cores"`
	MemoryGB    int64  `json:"memory_gb"`
	DiskGB      int64  `json:"disk_gb"`
	CustomImage string `json:"custom_image,omitempty"`
}

// VMCreateResponse — ответ на POST /api/vms.
type VMCreateResponse struct {
	Status string `json:"status"`
	Name   string `json:"name"`
	TaskID int64  `json:"task_id"`
}

// VM — представление ВМ, возвращаемое GET /api/vms/{name}.
type VM struct {
	Name     string   `json:"name"`
	Status   string   `json:"status"`
	OSType   string   `json:"os_type"`
	CPUCores int64    `json:"cpu_cores"`
	Memory   string   `json:"memory"`
	IPs      []string `json:"ips"`
	SSHPort  *int64   `json:"ssh_port"`
	HTTPPort *int64   `json:"http_port"`
	RDPPort  *int64   `json:"rdp_port"`
	Node     string   `json:"node"`
}

// PrimaryIP возвращает первый внешний IP или пустую строку.
func (v *VM) PrimaryIP() string {
	if len(v.IPs) > 0 {
		return v.IPs[0]
	}
	return ""
}

func (c *Client) CreateVM(ctx context.Context, in VMCreate) (*VMCreateResponse, error) {
	var out VMCreateResponse
	if err := c.do(ctx, http.MethodPost, "/vms", in, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) GetVM(ctx context.Context, name string) (*VM, error) {
	var out VM
	if err := c.do(ctx, http.MethodGet, "/vms/"+name, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) DeleteVM(ctx context.Context, name string) error {
	err := c.do(ctx, http.MethodDelete, "/vms/"+name, nil, nil)
	if errors.Is(err, ErrNotFound) {
		return nil // уже удалена — не ошибка
	}
	return err
}

// ------------------------------- Базы данных --------------------------------

// DBCreate — тело запроса на создание БД.
type DBCreate struct {
	Name   string `json:"name"`
	Engine string `json:"engine,omitempty"`
}

// Database — ответ API с параметрами базы данных.
type Database struct {
	ID         int64  `json:"id"`
	DBName     string `json:"db_name"`
	Engine     string `json:"engine"`
	DBUser     string `json:"db_user"`
	DBPassword string `json:"db_password"`
	Status     string `json:"status"`
	DBHost     string `json:"db_host"`
}

func (c *Client) CreateDatabase(ctx context.Context, in DBCreate) (*Database, error) {
	var out Database
	if err := c.do(ctx, http.MethodPost, "/databases", in, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetDatabase ищет БД по числовому id. Отдельного GET-эндпоинта нет,
// поэтому берём список и фильтруем.
func (c *Client) GetDatabase(ctx context.Context, id int64) (*Database, error) {
	var list []Database
	if err := c.do(ctx, http.MethodGet, "/databases", nil, &list); err != nil {
		return nil, err
	}
	for i := range list {
		if list[i].ID == id {
			return &list[i], nil
		}
	}
	return nil, ErrNotFound
}

func (c *Client) DeleteDatabase(ctx context.Context, id int64) error {
	err := c.do(ctx, http.MethodDelete, fmt.Sprintf("/databases/%d", id), nil, nil)
	if errors.Is(err, ErrNotFound) {
		return nil
	}
	return err
}
