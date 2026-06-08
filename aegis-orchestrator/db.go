package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

var dbPool *pgxpool.Pool

func initDB() {
	connStr := os.Getenv("DB_CONN_STR")
	if connStr == "" {
		connStr = "postgresql://postgres:postgres@localhost:5432/aegis?sslmode=disable"
	}

	var err error
	// Retry database connection a few times in case Postgres is starting up
	for i := 0; i < 10; i++ {
		dbPool, err = pgxpool.New(context.Background(), connStr)
		if err == nil {
			err = dbPool.Ping(context.Background())
			if err == nil {
				break
			}
		}
		log.Printf("[DB] Ожидание запуска базы данных... Попытка %d/10. Ошибка: %v", i+1, err)
		time.Sleep(3 * time.Second)
	}

	if err != nil {
		log.Fatalf("[DB] Не удалось подключиться к базе данных: %v", err)
	}

	log.Println("[DB] Успешное подключение к PostgreSQL.")
	migrateSchema()
}

func migrateSchema() {
	ctx := context.Background()

	// 1. Создание таблицы system_state
	_, err := dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS system_state (
			id INT PRIMARY KEY,
			balance DOUBLE PRECISION DEFAULT 50.0,
			billing_rate DOUBLE PRECISION DEFAULT 0.0,
			ddos_active BOOLEAN DEFAULT FALSE
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы system_state: %v", err)
	}

	// Сид для system_state
	_, _ = dbPool.Exec(ctx, `
		INSERT INTO system_state (id, balance, billing_rate, ddos_active)
		VALUES (1, 50.0, 0.0, FALSE)
		ON CONFLICT (id) DO NOTHING
	`)

	// 2. Создание таблицы containers
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS containers (
			id VARCHAR PRIMARY KEY,
			name VARCHAR NOT NULL,
			status VARCHAR NOT NULL,
			cpu_cores INT NOT NULL,
			ram_limit_gb INT NOT NULL,
			cpu_pinning JSONB,
			namespaces JSONB,
			cgroup_path VARCHAR,
			pid INT
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы containers: %v", err)
	}

	// 3. Создание таблицы s3_nodes
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS s3_nodes (
			id VARCHAR PRIMARY KEY,
			name VARCHAR NOT NULL,
			path VARCHAR NOT NULL,
			status VARCHAR NOT NULL,
			disk_usage BIGINT DEFAULT 0,
			total_capacity BIGINT DEFAULT 0
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы s3_nodes: %v", err)
	}

	// 4. Создание таблицы ddos_rules
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS ddos_rules (
			id VARCHAR PRIMARY KEY,
			pps_threshold INT NOT NULL,
			action VARCHAR NOT NULL,
			active_rules JSONB
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы ddos_rules: %v", err)
	}

	// 5. Создание таблицы transactions
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS transactions (
			id SERIAL PRIMARY KEY,
			time VARCHAR NOT NULL,
			amount DOUBLE PRECISION NOT NULL,
			description VARCHAR NOT NULL
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы transactions: %v", err)
	}

	// 6. Создание таблицы ddos_logs
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS ddos_logs (
			id SERIAL PRIMARY KEY,
			time VARCHAR NOT NULL,
			source VARCHAR NOT NULL,
			type VARCHAR NOT NULL,
			pps INT NOT NULL,
			action VARCHAR NOT NULL
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы ddos_logs: %v", err)
	}

	// 7. Создание таблицы aws_security_groups
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS aws_security_groups (
			id VARCHAR PRIMARY KEY,
			name VARCHAR NOT NULL,
			description VARCHAR,
			rules JSONB,
			bound_instances JSONB
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы aws_security_groups: %v", err)
	}

	// 8. Создание таблицы aws_s3_buckets
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS aws_s3_buckets (
			name VARCHAR PRIMARY KEY,
			region VARCHAR DEFAULT 'us-east-1',
			access_policy VARCHAR DEFAULT 'Private',
			objects JSONB
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы aws_s3_buckets: %v", err)
	}

	// 9. Создание таблицы aws_iam_users
	_, err = dbPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS aws_iam_users (
			username VARCHAR PRIMARY KEY,
			policy TEXT NOT NULL,
			joined_at VARCHAR NOT NULL
		)
	`)
	if err != nil {
		log.Fatalf("[DB] Ошибка создания таблицы aws_iam_users: %v", err)
	}

	log.Println("[DB] Все таблицы базы данных успешно верифицированы/мигрированы.")
}

// Сериализация в JSON
func toJSONB(val interface{}) []byte {
	bytes, err := json.Marshal(val)
	if err != nil {
		return []byte("[]")
	}
	return bytes
}
