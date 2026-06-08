package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
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

const awsStateFile = "/app/data/aegis_aws_state.json"

func init() {
	loadAWSState()
}

func loadAWSState() {
	data, err := os.ReadFile(awsStateFile)
	if err == nil {
		var loaded AWSState
		if err := json.Unmarshal(data, &loaded); err == nil {
			awsState.SecurityGroups = loaded.SecurityGroups
			awsState.S3Buckets = loaded.S3Buckets
			awsState.IAMUsers = loaded.IAMUsers
		}
	}
}

func saveAWSState() {
	data, err := json.MarshalIndent(awsState, "", "  ")
	if err == nil {
		_ = os.WriteFile(awsStateFile, data, 0644)
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

// Compiles stateful rules to actual Linux iptables rules
func ApplySecurityGroupRules(containerID string, rules []SecurityGroupRule) {
	fmt.Printf("[AWS-VPC] Компиляция Security Group правил для контейнера %s...\n", containerID)

	if runtime.GOOS != "linux" {
		fmt.Printf("[AWS-VPC] [СИМУЛЯЦИЯ] Загружены правила фаервола Security Group (%d правил) в iptables пространства имен %s\n", len(rules), containerID)
		return
	}

	// For real Linux: we find the container PID and execute iptables commands inside the container's net namespace
	// We run: ip netns exec <ns> iptables -F INPUT (etc.)
	// Since our containers run in custom namespaces, we can enter the net namespace of the container PID:
	// "nsenter -t <pid> -n iptables ..."
	
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
		cmdStr := fmt.Sprintf("nsenter -t %d -n iptables -F INPUT", containerPID)
		_ = exec.Command("/bin/sh", "-c", cmdStr).Run()

		// 2. Set default policy to DROP for INPUT (Stateful incoming firewall)
		_ = exec.Command("/bin/sh", "-c", fmt.Sprintf("nsenter -t %d -n iptables -P INPUT DROP", containerPID)).Run()

		// 3. Allow established/related sessions (Stateful rule!)
		_ = exec.Command("/bin/sh", "-c", fmt.Sprintf("nsenter -t %d -n iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT", containerPID)).Run()

		// 4. Loop through and apply rules
		for _, r := range rules {
			if r.Type != "Inbound" {
				continue
			}
			
			// Build iptables rule
			ruleCmd := fmt.Sprintf("nsenter -t %d -n iptables -A INPUT -p %s", containerPID, r.Protocol)
			if r.PortRange != "all" && r.PortRange != "" {
				ruleCmd += fmt.Sprintf(" --dport %s", r.PortRange)
			}
			if r.Source != "0.0.0.0/0" && r.Source != "" {
				ruleCmd += fmt.Sprintf(" -s %s", r.Source)
			}
			ruleCmd += " -j ACCEPT"

			_ = exec.Command("/bin/sh", "-c", ruleCmd).Run()
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
