package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os/exec"
	"regexp"
	"runtime"
	"strings"
	"sync"
)

type SecurityGroupRule struct {
	Type      string `json:"type"`       // Inbound, Outbound
	Protocol  string `json:"protocol"`   // tcp, udp, icmp
	PortRange string `json:"port_range"` // e.g. "80", "22", "1-65535"
	Source    string `json:"source"`     // e.g. "0.0.0.0/0", "192.168.1.1/32"
}

type SecurityGroup struct {
	ID             string              `json:"id"`
	Name           string              `json:"name"`
	Description    string              `json:"description"`
	Rules          []SecurityGroupRule `json:"rules"`
	BoundInstances []string            `json:"bound_instances"`
}

type S3BucketObject struct {
	Key        string `json:"key"`
	Size       int64  `json:"size"`
	LastUpdate string `json:"last_update"`
}

type S3Bucket struct {
	Name         string           `json:"name"`
	Region       string           `json:"region"`
	AccessPolicy string           `json:"access_policy"` // Private, Public-Read
	Objects      []S3BucketObject `json:"objects"`
}

type IAMStatement struct {
	Effect   string   `json:"Effect"` // Allow, Deny
	Action   []string `json:"Action"`
	Resource string   `json:"Resource"`
}

type IAMPolicy struct {
	Version   string         `json:"Version"`
	Statement []IAMStatement `json:"Statement"`
}

type IAMUser struct {
	Username string   `json:"username"`
	Policy   string   `json:"policy"` // JSON policy document
	JoinedAt string   `json:"joined_at"`
}

// Global AWS States
type AWSState struct {
	mu             sync.RWMutex
	SecurityGroups []*SecurityGroup `json:"security_groups"`
	S3Buckets      []*S3Bucket      `json:"s3_buckets"`
	IAMUsers       []*IAMUser       `json:"iam_users"`
}

var awsState = &AWSState{
	SecurityGroups: []*SecurityGroup{
		{
			ID:          "sg-01a2b3c4d",
			Name:        "default-vpc-sg",
			Description: "Стандартная группа безопасности VPC",
			Rules: []SecurityGroupRule{
				{Type: "Inbound", Protocol: "tcp", PortRange: "22", Source: "0.0.0.0/0"},
				{Type: "Inbound", Protocol: "tcp", PortRange: "80", Source: "0.0.0.0/0"},
				{Type: "Inbound", Protocol: "tcp", PortRange: "443", Source: "0.0.0.0/0"},
				{Type: "Outbound", Protocol: "all", PortRange: "all", Source: "0.0.0.0/0"},
			},
			BoundInstances: []string{"client-my-db-vds", "client-web-app"},
		},
		{
			ID:          "sg-09f8e7d6c",
			Name:        "secure-database-sg",
			Description: "Разрешает доступ к СУБД только из внутренней сети",
			Rules: []SecurityGroupRule{
				{Type: "Inbound", Protocol: "tcp", PortRange: "5432", Source: "10.0.99.0/24"},
				{Type: "Inbound", Protocol: "tcp", PortRange: "22", Source: "185.190.140.0/24"},
				{Type: "Outbound", Protocol: "all", PortRange: "all", Source: "0.0.0.0/0"},
			},
			BoundInstances: []string{"client-redis-billing-server"},
		},
	},
	S3Buckets: []*S3Bucket{
		{
			Name:         "aegis-backups-bucket",
			Region:       "us-east-1",
			AccessPolicy: "Private",
			Objects: []S3BucketObject{
				{Key: "db-backup-2026-06-07.sql", Size: 154820, LastUpdate: "2026-06-07 14:02:11"},
				{Key: "web-config.json", Size: 1242, LastUpdate: "2026-06-08 09:12:00"},
			},
		},
	},
	IAMUsers: []*IAMUser{
		{
			Username: "admin-operator",
			JoinedAt: "2026-06-08 10:00:00",
			Policy: `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:*", "s3:*", "iam:*"],
      "Resource": "*"
    }
  ]
}`,
		},
		{
			Username: "dev-developer",
			JoinedAt: "2026-06-08 10:15:00",
			Policy: `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:StartInstance", "ec2:StopInstance", "s3:ListBucket"],
      "Resource": "*"
    },
    {
      "Effect": "Deny",
      "Action": ["ec2:TerminateInstance"],
      "Resource": "*"
    }
  ]
}`,
		},
	},
}

func init() {
	// init will be called, but wait for dbPool setup in main.
	// Since loadAWSState needs dbPool, we will call it from main after initDB.
}

func loadAWSState() {
	awsState.mu.Lock()
	defer awsState.mu.Unlock()

	ctx := context.Background()

	// 1. Загрузка Security Groups
	rows, err := dbPool.Query(ctx, "SELECT id, name, description, rules, bound_instances FROM aws_security_groups")
	if err == nil {
		defer rows.Close()
		awsState.SecurityGroups = []*SecurityGroup{}
		for rows.Next() {
			var sg SecurityGroup
			var rulesBytes, boundBytes []byte
			err := rows.Scan(&sg.ID, &sg.Name, &sg.Description, &rulesBytes, &boundBytes)
			if err == nil {
				_ = json.Unmarshal(rulesBytes, &sg.Rules)
				_ = json.Unmarshal(boundBytes, &sg.BoundInstances)
				awsState.SecurityGroups = append(awsState.SecurityGroups, &sg)
			}
		}
	}

	// 2. Загрузка S3 Buckets
	bRows, err := dbPool.Query(ctx, "SELECT name, region, access_policy, objects FROM aws_s3_buckets")
	if err == nil {
		defer bRows.Close()
		awsState.S3Buckets = []*S3Bucket{}
		for bRows.Next() {
			var b S3Bucket
			var objBytes []byte
			err := bRows.Scan(&b.Name, &b.Region, &b.AccessPolicy, &objBytes)
			if err == nil {
				_ = json.Unmarshal(objBytes, &b.Objects)
				awsState.S3Buckets = append(awsState.S3Buckets, &b)
			}
		}
	}

	// 3. Загрузка IAM Users
	uRows, err := dbPool.Query(ctx, "SELECT username, policy, joined_at FROM aws_iam_users")
	if err == nil {
		defer uRows.Close()
		awsState.IAMUsers = []*IAMUser{}
		for uRows.Next() {
			var u IAMUser
			err := uRows.Scan(&u.Username, &u.Policy, &u.JoinedAt)
			if err == nil {
				awsState.IAMUsers = append(awsState.IAMUsers, &u)
			}
		}
	}
}

func saveAWSState() {
	awsState.mu.RLock()
	defer awsState.mu.RUnlock()

	ctx := context.Background()

	// Очищаем и перезаписываем для простоты
	_, _ = dbPool.Exec(ctx, "DELETE FROM aws_security_groups")
	for _, sg := range awsState.SecurityGroups {
		_, _ = dbPool.Exec(ctx, "INSERT INTO aws_security_groups (id, name, description, rules, bound_instances) VALUES ($1, $2, $3, $4, $5)",
			sg.ID, sg.Name, sg.Description, toJSONB(sg.Rules), toJSONB(sg.BoundInstances))
	}

	_, _ = dbPool.Exec(ctx, "DELETE FROM aws_s3_buckets")
	for _, b := range awsState.S3Buckets {
		_, _ = dbPool.Exec(ctx, "INSERT INTO aws_s3_buckets (name, region, access_policy, objects) VALUES ($1, $2, $3, $4)",
			b.Name, b.Region, b.AccessPolicy, toJSONB(b.Objects))
	}

	_, _ = dbPool.Exec(ctx, "DELETE FROM aws_iam_users")
	for _, u := range awsState.IAMUsers {
		_, _ = dbPool.Exec(ctx, "INSERT INTO aws_iam_users (username, policy, joined_at) VALUES ($1, $2, $3)",
			u.Username, u.Policy, u.JoinedAt)
	}
}

// AWS IAM JSON Policy checker
func CheckIAMPermission(username, action, resource string) bool {
	awsState.mu.RLock()
	defer awsState.mu.RUnlock()

	var user *IAMUser
	for _, u := range awsState.IAMUsers {
		if u.Username == username {
			user = u
			break
		}
	}
	if user == nil {
		return false
	}

	var policy IAMPolicy
	err := json.Unmarshal([]byte(user.Policy), &policy)
	if err != nil {
		// Invalid JSON policy
		return false
	}

	allowed := false
	for _, stmt := range policy.Statement {
		// Check Resource match (simple wildcard check)
		if stmt.Resource != "*" && stmt.Resource != resource {
			continue
		}

		// Check Action match
		actionMatch := false
		for _, act := range stmt.Action {
			if act == "*" || act == action {
				actionMatch = true
				break
			}
			// Prefix wildcard match (e.g. "ec2:*")
			if strings.HasSuffix(act, ":*") {
				prefix := strings.Split(act, ":")[0]
				reqPrefix := strings.Split(action, ":")[0]
				if prefix == reqPrefix {
					actionMatch = true
					break
				}
			}
		}

		if actionMatch {
			if stmt.Effect == "Deny" {
				return false // Explicit Deny wins in AWS!
			}
			if stmt.Effect == "Allow" {
				allowed = true
			}
		}
	}

	return allowed
}

var (
	protocolRegex  = regexp.MustCompile(`^(?i:tcp|udp|icmp|all)$`)
	portRangeRegex = regexp.MustCompile(`^(?i:all)$|^\d+$|^\d+-\d+$`)
	sourceRegex    = regexp.MustCompile(`^[a-zA-Z0-9./:]+$`)
)

func ValidateSecurityGroupRules(rules []SecurityGroupRule) error {
	for i, r := range rules {
		if r.Type != "Inbound" && r.Type != "Outbound" {
			return fmt.Errorf("rule %d: invalid type (must be Inbound or Outbound): %s", i, r.Type)
		}
		if r.Protocol == "" {
			return fmt.Errorf("rule %d: protocol cannot be empty", i)
		}
		if !protocolRegex.MatchString(r.Protocol) {
			return fmt.Errorf("rule %d: invalid protocol: %s", i, r.Protocol)
		}
		if r.PortRange != "" && !portRangeRegex.MatchString(r.PortRange) {
			return fmt.Errorf("rule %d: invalid port range: %s", i, r.PortRange)
		}
		if r.Source != "" && !sourceRegex.MatchString(r.Source) {
			return fmt.Errorf("rule %d: invalid source: %s", i, r.Source)
		}
	}
	return nil
}

// Compiles stateful rules to actual Linux iptables rules
func ApplySecurityGroupRules(containerID string, rules []SecurityGroupRule) {
	fmt.Printf("[AWS-VPC] Компиляция Security Group правил для контейнера %s...\n", containerID)

	if runtime.GOOS != "linux" {
		fmt.Printf("[AWS-VPC] [СИМУЛЯЦИЯ] Загружены правила фаервола Security Group (%d правил) в iptables пространства имен %s\n", len(rules), containerID)
		return
	}

	state.mu.RLock()
	var containerPID int
	for _, c := range state.Containers {
		if c.ID == containerID {
			containerPID = c.PID
			break
		}
	}
	state.mu.RUnlock()

	if containerPID <= 0 {
		return
	}

	go func() {
		// 1. Flush INPUT rules inside container net namespace
		_ = exec.Command("nsenter", "-t", fmt.Sprintf("%d", containerPID), "-n", "iptables", "-F", "INPUT").Run()

		// 2. Set default policy to DROP for INPUT (Stateful incoming firewall)
		_ = exec.Command("nsenter", "-t", fmt.Sprintf("%d", containerPID), "-n", "iptables", "-P", "INPUT", "DROP").Run()

		// 3. Allow established/related sessions (Stateful rule!)
		_ = exec.Command("nsenter", "-t", fmt.Sprintf("%d", containerPID), "-n", "iptables", "-A", "INPUT", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT").Run()

		// 4. Loop through and apply rules
		for _, r := range rules {
			if r.Type != "Inbound" {
				continue
			}

			// Validate rule again (just in case)
			if !protocolRegex.MatchString(r.Protocol) ||
				(r.PortRange != "" && !portRangeRegex.MatchString(r.PortRange)) ||
				(r.Source != "" && !sourceRegex.MatchString(r.Source)) {
				fmt.Printf("[AWS-VPC] Пропуск некорректного правила Security Group: %+v\n", r)
				continue
			}

			// Build args list for exec.Command
			args := []string{"-t", fmt.Sprintf("%d", containerPID), "-n", "iptables", "-A", "INPUT"}
			
			proto := strings.ToLower(r.Protocol)
			if proto != "all" {
				args = append(args, "-p", proto)
				if r.PortRange != "all" && r.PortRange != "" {
					args = append(args, "--dport", r.PortRange)
				}
			} else {
				if r.PortRange != "all" && r.PortRange != "" {
					fmt.Printf("[AWS-VPC] Предупреждение: --dport %s не может быть применен для протокола 'all'. Игнорируем порт.\n", r.PortRange)
				}
			}

			if r.Source != "0.0.0.0/0" && r.Source != "" {
				args = append(args, "-s", r.Source)
			}
			args = append(args, "-j", "ACCEPT")

			_ = exec.Command("nsenter", args...).Run()
		}

		fmt.Printf("[AWS-VPC] Успешно применены правила iptables для PID %d\n", containerPID)
	}()
}

func handleAWSStatus(w http.ResponseWriter, r *http.Request) {
	awsState.mu.RLock()
	defer awsState.mu.RUnlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(awsState)
}
