from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
import os
import re
import socket
import paramiko
import secrets
import string
import hashlib

def generate_mac_address(name: str) -> str:
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    # 02:00:00 prefix ensures it's a locally administered unicast MAC
    return f"02:00:00:{h[0:2]}:{h[2:4]}:{h[4:6]}"

import logging
from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from app.core.k8s_client import K8sClient
from app.services.ssh_inspector import SSHInspector

router = APIRouter()
logger = logging.getLogger("app.api.vms")

def get_host_ip() -> str:
    """Определяет IP хоста, доступный для подов K3s"""
    env_host = os.getenv("HOST_IP") or os.getenv("AEGIS_HOST_IP")
    if env_host:
        return env_host
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "127.0.0.1":
            return ip
    except Exception:
        pass
    return "172.20.0.1"

# Зависимость для получения клиента K8s
def get_k8s_client():
    return K8sClient()

# Модели запросов
class VMCreationRequest(BaseModel):
    name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя виртуалки (латиница, цифры, дефис)")
    os_type: str = Field(..., description="Тип ОС (ubuntu, windows или custom)")
    custom_image: Optional[str] = Field(None, description="Имя файла кастомного образа (если os_type == custom)")
    cpu_cores: int = Field(2, ge=1, le=16, description="Количество ядер CPU")
    memory_gb: int = Field(2, ge=1, le=64, description="Объем оперативной памяти в ГБ")
    disk_gb: int = Field(20, ge=10, le=500, description="Размер системного диска в ГБ")
    iso_url: Optional[str] = Field(None, description="Ссылка на собственный ISO-образ (для Windows)")
    packages: Optional[str] = Field(None, description="Пакеты для установки (через запятую)")
    network_drives: Optional[str] = Field(None, description="Сетевые диски (NFS/PVC через запятую)")

class VMResizeRequest(BaseModel):
    cpu_cores: int = Field(..., ge=1, le=16)
    memory_gb: int = Field(..., ge=1, le=64)
    disk_gb: int = Field(..., ge=10, le=500)

class PortConfigItem(BaseModel):
    ext_port: int
    int_port: int
    name: str

class VMSettingsUpdateRequest(BaseModel):
    cpu_cores: int = Field(..., ge=1, le=16)
    memory_gb: int = Field(..., ge=1, le=64)
    disk_gb: int = Field(..., ge=10, le=500)
    # Storage Throttling (Disk Limits)
    disk_read_mbs: int = Field(0, ge=0, le=1000)
    disk_write_mbs: int = Field(0, ge=0, le=1000)
    disk_read_iops: int = Field(0, ge=0, le=10000)
    disk_write_iops: int = Field(0, ge=0, le=10000)
    # Port configuration and firewall
    ports_config: Optional[List[PortConfigItem]] = None
    firewall_rules: Optional[List[dict]] = None # List of {"port": int, "allowed_ips": ["1.2.3.4"]}

def generate_random_password(length=12) -> str:
    """Генерирует криптографически стойкий случайный пароль"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

# Базовые константы-шаблоны для генерации манифестов
DEFAULT_WINDOWS_ISO = "https://go.microsoft.com/fwlink/p/?LinkID=2195280"
DEFAULT_UBUNTU_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
DEFAULT_CENTOS_IMAGE = "https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2"
DEFAULT_DEBIAN_IMAGE = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
DEFAULT_PROXMOX_ISO = "http://download.proxmox.com/iso/proxmox-ve_8.2-1.iso"

def generate_linux_manifest(req: VMCreationRequest, password: str) -> dict:
    # Определение базового образа и логина
    image_url = DEFAULT_UBUNTU_IMAGE
    default_user = "ubuntu"
    
    if req.os_type == "centos":
        image_url = DEFAULT_CENTOS_IMAGE
        default_user = "cloud-user"
    elif req.os_type == "debian":
        image_url = DEFAULT_DEBIAN_IMAGE
        default_user = "debian"
    elif req.os_type == "bitrix":
        image_url = DEFAULT_CENTOS_IMAGE
        default_user = "cloud-user"
    elif req.os_type == "custom" and req.custom_image:
        host_ip = get_host_ip()
        image_url = f"http://{host_ip}:8000/static/images/{req.custom_image}"
        

    # Обработка пакетов
    packages_yaml = ""
    if req.packages:
        pkgs = [p.strip() for p in req.packages.split(",") if p.strip()]
        if pkgs:
            packages_yaml = "\npackages:\n" + "\n".join([f"  - {p}" for p in pkgs])
            
    # Обработка сетевых дисков
    mounts_yaml = ""
    extra_volumes = []
    extra_disks = []
    
    if req.network_drives:
        drives = [d.strip() for d in req.network_drives.split(",") if d.strip()]
        mounts_list = []
        for idx, drive in enumerate(drives):
            if ":/" in drive:
                mounts_list.append(f"  - [ {drive}, /mnt/network_drive_{idx}, nfs, \"defaults\", \"0\", \"0\" ]")
            else:
                vol_name = f"net-pvc-{idx}"
                extra_volumes.append({
                    "name": vol_name,
                    "persistentVolumeClaim": {
                        "claimName": drive
                    }
                })
                extra_disks.append({
                    "name": vol_name,
                    "disk": {
                        "bus": "virtio"
                    }
                })
        
        if mounts_list:
            mounts_yaml = "\nmounts:\n" + "\n".join(mounts_list)
            if "nfs-common" not in packages_yaml:
                if packages_yaml:
                    packages_yaml += "\n  - nfs-common"
                else:
                    packages_yaml = "\npackages:\n  - nfs-common"

    # Специфично для Bitrix
    runcmd_yaml = ""
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            if packages_yaml:
                packages_yaml += "\n  - wget"
            else:
                packages_yaml = "\npackages:\n  - wget"
        runcmd_yaml = "\n  - wget http://repos.1c-bitrix.ru/yum/bitrix-env.sh\n  - chmod +x bitrix-env.sh\n  - ./bitrix-env.sh -s -p -H " + req.name + "\n"

    manifest = {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": req.name,
            "namespace": "default",
            "labels": {
                "hosting.antigravity.io/template": req.os_type,
                **({"hosting.antigravity.io/owner": "client-01"} if req.name.startswith("client-") else {})
            }
        },
        "spec": {
            "running": True,
            "template": {
                "metadata": {
                    "labels": {
                        "kubevirt.io/domain": req.name
                    }
                },
                "spec": {
                    "domain": {
                        "cpu": {
                            "cores": req.cpu_cores
                        },
                        "resources": {
                            "requests": {
                                "memory": f"{req.memory_gb}Gi"
                            }
                        },
                        "devices": {
                            "disks": [
                                {
                                    "name": "datavolume",
                                    "disk": {
                                        "bus": "virtio"
                                    }
                                },
                                {
                                    "name": "cloudinit",
                                    "cdrom": {
                                        "bus": "sata"
                                    }
                                }
                            ],
                            "interfaces": [
                                {
                                    "name": "default",
                                    "masquerade": {}
                                }
                            ],
                            "inputs": [
                                {
                                    "type": "tablet",
                                    "name": "tablet",
                                    "bus": "usb"
                                }
                            ]
                        }
                    },
                    "networks": [
                        {
                            "name": "default",
                            "pod": {}
                        }
                    ],
                    "volumes": [
                        {
                            "name": "datavolume",
                            "dataVolume": {
                                "name": f"{req.name}-disk"
                            }
                        },
                        {
                            "name": "cloudinit",
                            "cloudInitNoCloud": {
                                "userData": f"""#cloud-config
ssh_pwauth: True
disable_root: false
chpasswd:
  list: |
    root:{password}
    {default_user}:{password}
  expire: False
users:
  - default
{packages_yaml}{mounts_yaml}
write_files:
  - path: /etc/netplan/99-dhcp.yaml
    content: |
      network:
        version: 2
        ethernets:
          all-eth:
            match:
              name: "e*"
            dhcp4: true
  - path: /etc/systemd/system/getty@tty1.service.d/override.conf
    content: |
      [Service]
      ExecStart=
      ExecStart=-/sbin/agetty --autologin {default_user} --noclear %I $TERM
runcmd:
  - echo "root:{password}" | chpasswd
  - echo "{default_user}:{password}" | chpasswd
  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
  - sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config.d/*.conf || true
  - systemctl restart ssh || systemctl restart sshd || true
  - (netplan apply || systemctl restart systemd-networkd || nmcli con reload) || true
  - systemctl daemon-reload || true
  - systemctl restart getty@tty1.service || true
  - while ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; do sleep 2; done
  - i=1; while [ $i -le 50 ]; do (apt-get update && apt-get install -y qemu-guest-agent) && break || (dnf install -y qemu-guest-agent) && break || (yum install -y qemu-guest-agent) && break || sleep 5; i=$((i+1)); done || true
  - systemctl enable --now qemu-guest-agent || true{runcmd_yaml}
""",
                                "metaData": f"""instance-id: {req.name}
local-hostname: {req.name}
"""
                            }
                        }
                    ]
                }
            },
            "dataVolumeTemplates": [
                {
                    "metadata": {
                        "name": f"{req.name}-disk",
                        "annotations": {
                            "cdi.kubevirt.io/storage.bind.immediate.requested": "true"
                        }
                    },
                    "spec": {
                        "source": {
                            "http": {
                                "url": image_url
                            }
                        },
                        "storage": {
                            "storageClassName": "local-path",
                            "accessModes": [
                                "ReadWriteOnce"
                            ],
                            "volumeMode": "Filesystem",
                            "resources": {
                                "requests": {
                                    "storage": f"{req.disk_gb}Gi"
                                }
                            }
                        }
                    }
                }
            ]
        }
    }
    # Инжектим дополнительные диски (PVC)
    if extra_disks:
        manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"].extend(extra_disks)
        manifest["spec"]["template"]["spec"]["volumes"].extend(extra_volumes)
        
    return manifest

def generate_windows_manifest(req: VMCreationRequest) -> dict:
    iso_url = req.iso_url or DEFAULT_WINDOWS_ISO
    # Если Windows создается из кастомного образа ISO
    if req.os_type == "custom" and req.custom_image:
        host_ip = get_host_ip()
        iso_url = f"http://{host_ip}:8000/static/images/{req.custom_image}"

    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": req.name,
            "namespace": "default",
            "labels": {
                "hosting.antigravity.io/template": "windows",
                **({"hosting.antigravity.io/owner": "client-01"} if req.name.startswith("client-") else {})
            }
        },
        "spec": {
            "running": True,
            "template": {
                "metadata": {
                    "labels": {
                        "kubevirt.io/domain": req.name
                    }
                },
                "spec": {
                    "domain": {
                        "cpu": {
                            "cores": req.cpu_cores
                        },
                        "resources": {
                            "requests": {
                                "memory": f"{req.memory_gb}Gi"
                            }
                        },
                        "features": {
                            "acpi": {},
                            "apic": {},
                            "hyperv": {
                                "relaxed": {},
                                "vapic": {},
                                "spinlocks": {
                                    "spinlocks": 8191
                                }
                            }
                        },
                        "devices": {
                            "disks": [
                                {
                                    "name": "winhd",
                                    "bootOrder": 2,
                                    "disk": {
                                        "bus": "virtio"
                                    }
                                },
                                {
                                    "name": "winiso",
                                    "bootOrder": 1,
                                    "cdrom": {
                                        "bus": "sata"
                                    }
                                },
                                {
                                    "name": "virtio-drivers",
                                    "cdrom": {
                                        "bus": "sata"
                                    }
                                }
                            ],
                            "interfaces": [
                                {
                                    "name": "default",
                                    "masquerade": {}
                                }
                            ],
                            "inputs": [
                                {
                                    "type": "tablet",
                                    "name": "tablet",
                                    "bus": "usb"
                                }
                            ]
                        }
                    },
                    "networks": [
                        {
                            "name": "default",
                            "pod": {}
                        }
                    ],
                    "volumes": [
                        {
                            "name": "winhd",
                            "dataVolume": {
                                "name": f"{req.name}-hd"
                            }
                        },
                        {
                            "name": "winiso",
                            "dataVolume": {
                                "name": f"{req.name}-iso"
                            }
                        },
                        {
                            "name": "virtio-drivers",
                            "containerDisk": {
                                "image": "quay.io/kubevirt/virtio-container-disk:v1.0.0"
                            }
                        }
                    ]
                }
            },
            "dataVolumeTemplates": [
                {
                    "metadata": {
                        "name": f"{req.name}-hd",
                        "annotations": {
                            "cdi.kubevirt.io/storage.bind.immediate.requested": "true"
                        }
                    },
                    "spec": {
                        "source": {
                            "blank": {}
                        },
                        "storage": {
                            "storageClassName": "local-path",
                            "accessModes": [
                                "ReadWriteOnce"
                            ],
                            "volumeMode": "Filesystem",
                            "resources": {
                                "requests": {
                                    "storage": f"{req.disk_gb}Gi"
                                }
                            }
                        }
                    }
                },
                {
                    "metadata": {
                        "name": f"{req.name}-iso",
                        "annotations": {
                            "cdi.kubevirt.io/storage.bind.immediate.requested": "true"
                        }
                    },
                    "spec": {
                        "source": {
                            "http": {
                                "url": iso_url
                            }
                        },
                        "storage": {
                            "storageClassName": "local-path",
                            "accessModes": [
                                "ReadWriteOnce"
                            ],
                            "volumeMode": "Filesystem",
                            "resources": {
                                "requests": {
                                    "storage": "6Gi"
                                }
                            }
                        }
                    }
                }
            ]
        }
    }


@router.get("", response_model=List[dict])
def list_vms(client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.list_vms()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def clear_iptables_rules_for_ip(vm_ip: str):
    import subprocess
    nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
    
    # Clear PREROUTING rules
    res = subprocess.run(nsenter_prefix + ["iptables -t nat -S PREROUTING"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if vm_ip in line:
                del_cmd = line.replace("-A ", "-D ")
                subprocess.run(nsenter_prefix + [f"iptables -t nat {del_cmd}"], capture_output=True, timeout=5)
                
    # Clear FORWARD rules
    res = subprocess.run(nsenter_prefix + ["iptables -S FORWARD"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if vm_ip in line:
                del_cmd = line.replace("-A ", "-D ")
                subprocess.run(nsenter_prefix + [f"iptables {del_cmd}"], capture_output=True, timeout=5)

def reconcile_vm_firewall_rules(vm_ip: str, ports_config: str = None, firewall_rules: str = None):
    """Настраивает проброс портов и правила доступа для ВМ с помощью iptables на хосте"""
    import subprocess
    import json
    try:
        last_octet = int(vm_ip.split('.')[-1])
        nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
        
        # Очищаем старые правила
        clear_iptables_rules_for_ip(vm_ip)
        
        # Парсим список портов
        ports = []
        if ports_config:
            try:
                ports = json.loads(ports_config)
            except Exception as e:
                logger.error(f"Error parsing ports_config: {e}")
                
        # Если порты не настроены, используем дефолтные
        if not ports:
            ports = [
                {"ext_port": 22000 + last_octet, "int_port": 22, "name": "SSH"},
                {"ext_port": 28000 + last_octet, "int_port": 80, "name": "HTTP"},
                {"ext_port": 44300 + last_octet, "int_port": 443, "name": "HTTPS"}
            ]
            
        # Парсим список разрешенных IP
        fw_map = {}
        if firewall_rules:
            try:
                rules_list = json.loads(firewall_rules)
                for r in rules_list:
                    port_val = r.get("port")
                    if port_val is not None:
                        fw_map[int(port_val)] = r.get("allowed_ips", [])
            except Exception as e:
                logger.error(f"Error parsing firewall_rules: {e}")
                
        # Применяем правила для каждого порта
        for p in ports:
            ext_port = int(p.get("ext_port"))
            int_port = int(p.get("int_port"))
            
            # 1. Добавляем DNAT правило в PREROUTING
            add_dnat = f"iptables -t nat -A PREROUTING -p tcp --dport {ext_port} -j DNAT --to-destination {vm_ip}:{int_port}"
            subprocess.run(nsenter_prefix + [add_dnat], capture_output=True, timeout=5)
            
            # 2. Получаем белый список IP для этого порта
            whitelist = fw_map.get(int_port) or fw_map.get(ext_port) or []
            whitelist = [ip.strip() for ip in whitelist if ip.strip()]
            
            # Если белый список пуст или содержит 0.0.0.0/0, разрешаем всем
            if not whitelist or "0.0.0.0/0" in whitelist:
                add_forward = f"iptables -A FORWARD -p tcp -d {vm_ip} --dport {int_port} -j ACCEPT"
                subprocess.run(nsenter_prefix + [add_forward], capture_output=True, timeout=5)
            else:
                # Разрешаем доступ только для белого списка
                for ip_addr in whitelist:
                    add_allow = f"iptables -A FORWARD -p tcp -s {ip_addr} -d {vm_ip} --dport {int_port} -j ACCEPT"
                    subprocess.run(nsenter_prefix + [add_allow], capture_output=True, timeout=5)
                # Все остальное для этого порта сбрасываем
                add_drop = f"iptables -A FORWARD -p tcp -d {vm_ip} --dport {int_port} -j DROP"
                subprocess.run(nsenter_prefix + [add_drop], capture_output=True, timeout=5)
                
        # Сохраняем правила
        subprocess.run(nsenter_prefix + ["netfilter-persistent save"], capture_output=True, timeout=5)
        logger.info(f"Firewall reconciled successfully for {vm_ip}")
    except Exception as e:
        logger.error(f"Error in reconcile_vm_firewall_rules for {vm_ip}: {e}")

@router.get("/balancer/resources", response_model=List[dict])
def get_balancer_resources(client: K8sClient = Depends(get_k8s_client)):
    try:
        # 1. List all VMs to get their configurations (CPU limit, RAM limit)
        vms = client.list_vms()
        vms_map = {vm["name"]: vm for vm in vms}
        
        # 2. Query Prometheus for CPU usage
        cpu_query = 'sum(rate(container_cpu_usage_seconds_total{container="compute",pod=~"virt-launcher-.*"}[2m])) by (pod)'
        ram_query = 'container_memory_working_set_bytes{container="compute",pod=~"virt-launcher-.*"}'
        
        cpu_res = client.query_prometheus(cpu_query)
        ram_res = client.query_prometheus(ram_query)
        
        # Parse CPU results
        cpu_data = {}
        if cpu_res and cpu_res.get("status") == "success":
            for item in cpu_res.get("data", {}).get("result", []):
                pod = item.get("metric", {}).get("pod", "")
                val = float(item.get("value", [0, 0])[1])
                cpu_data[pod] = val
                
        # Parse RAM results
        ram_data = {}
        if ram_res and ram_res.get("status") == "success":
            for item in ram_res.get("data", {}).get("result", []):
                pod = item.get("metric", {}).get("pod", "")
                val = float(item.get("value", [0, 0])[1])
                ram_data[pod] = val
                
        # Combine data by matching VM names
        balancer_stats = []
        for vm_name, vm in vms_map.items():
            if vm.get("status") != "Running":
                continue
                
            # Find the corresponding pod
            pod_name = None
            cpu_val = 0.0
            ram_val = 0.0
            
            for pod in cpu_data.keys():
                if pod.startswith(f"virt-launcher-{vm_name}-"):
                    pod_name = pod
                    cpu_val = cpu_data[pod]
                    break
                    
            for pod in ram_data.keys():
                if pod.startswith(f"virt-launcher-{vm_name}-"):
                    pod_name = pod
                    ram_val = ram_data[pod]
                    break
            
            if not pod_name:
                continue
                
            # RAM limit
            ram_limit_gb = float(vm.get("memory_gb", vm.get("memory", 2)))
            ram_limit_mb = ram_limit_gb * 1024
            cpu_limit = float(vm.get("cpu_cores", 2))
            
            cpu_percent = round((cpu_val / cpu_limit) * 100, 1) if cpu_limit > 0 else 0.0
            ram_usage_mb = round(ram_val / (1024 * 1024), 1)
            ram_percent = round((ram_usage_mb / ram_limit_mb) * 100, 1) if ram_limit_mb > 0 else 0.0
            
            balancer_stats.append({
                "vm_name": vm_name,
                "pod_name": pod_name,
                "cpu_usage_cores": round(cpu_val, 3),
                "cpu_limit_cores": cpu_limit,
                "cpu_usage_percent": min(cpu_percent, 100.0),
                "memory_usage_mb": ram_usage_mb,
                "memory_limit_mb": ram_limit_mb,
                "memory_usage_percent": min(ram_percent, 100.0)
            })
            
        return balancer_stats
    except Exception as e:
        logger.error(f"Error in balancer resources: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}", response_model=dict)
def get_vm_details(name: str, client: K8sClient = Depends(get_k8s_client)):
    from app.db import SessionLocal
    from app.models.models import VMTask
    
    try:
        vm_data = client.get_vm(name)
        
        # Загружаем лимиты и сетевые настройки из БД
        db = SessionLocal()
        try:
            db_vm = db.query(VMTask).filter(VMTask.name == name).first()
            if db_vm:
                vm_data["disk_read_mbs"] = db_vm.disk_read_mbs
                vm_data["disk_write_mbs"] = db_vm.disk_write_mbs
                vm_data["disk_read_iops"] = db_vm.disk_read_iops
                vm_data["disk_write_iops"] = db_vm.disk_write_iops
                
                # Парсим JSON портов
                import json
                try:
                    vm_data["ports_config"] = json.loads(db_vm.ports_config) if db_vm.ports_config else []
                except Exception:
                    vm_data["ports_config"] = []
                try:
                    vm_data["firewall_rules"] = json.loads(db_vm.firewall_rules) if db_vm.firewall_rules else []
                except Exception:
                    vm_data["firewall_rules"] = []
                
                # Если виртуальная машина активна и получила IP-адрес, автоматически пробрасываем порт
                if vm_data.get("status") == "Running" and vm_data.get("ips"):
                    ip = vm_data["ips"][0]
                    reconcile_vm_firewall_rules(ip, db_vm.ports_config, db_vm.firewall_rules)
        finally:
            db.close()
            
        # Получаем данные о текущей скорости диска из Prometheus
        try:
            read_speed_query = f'sum(rate(container_fs_reads_bytes_total{{container=\"compute\",pod=~\"virt-launcher-{name}-.*\"}}[2m]))'
            write_speed_query = f'sum(rate(container_fs_writes_bytes_total{{container=\"compute\",pod=~\"virt-launcher-{name}-.*\"}}[2m]))'
            read_iops_query = f'sum(rate(container_fs_reads_total{{container=\"compute\",pod=~\"virt-launcher-{name}-.*\"}}[2m]))'
            write_iops_query = f'sum(rate(container_fs_writes_total{{container=\"compute\",pod=~\"virt-launcher-{name}-.*\"}}[2m]))'
            
            read_res = client.query_prometheus(read_speed_query)
            write_res = client.query_prometheus(write_speed_query)
            read_iops_res = client.query_prometheus(read_iops_query)
            write_iops_res = client.query_prometheus(write_iops_query)
            
            def parse_single_val(prom_data):
                if prom_data and prom_data.get("status") == "success":
                    results = prom_data.get("data", {}).get("result", [])
                    if results:
                        return float(results[0].get("value", [0, 0])[1])
                return 0.0
                
            vm_data["disk_read_speed_kbps"] = round(parse_single_val(read_res) / 1024, 2)
            vm_data["disk_write_speed_kbps"] = round(parse_single_val(write_res) / 1024, 2)
            vm_data["disk_read_iops_realtime"] = round(parse_single_val(read_iops_res), 2)
            vm_data["disk_write_iops_realtime"] = round(parse_single_val(write_iops_res), 2)
        except Exception as pe:
            logger.error(f"Error fetching realtime disk stats from Prometheus for {name}: {pe}")
            vm_data["disk_read_speed_kbps"] = 0.0
            vm_data["disk_write_speed_kbps"] = 0.0
            vm_data["disk_read_iops_realtime"] = 0.0
            vm_data["disk_write_iops_realtime"] = 0.0

        return vm_data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Виртуальная машина {name} не найдена: {e}")

@router.post("", status_code=status.HTTP_201_CREATED)
def create_vm(req: VMCreationRequest, client: K8sClient = Depends(get_k8s_client)):
    try:
        from app.db import SessionLocal
        from app.models.models import VMTask
        from app.queue_client import publish_task
        
        db = SessionLocal()
        
        # Проверяем, нет ли уже такой ВМ
        existing = db.query(VMTask).filter(VMTask.name == req.name).first()
        if existing:
            db.close()
            raise HTTPException(status_code=400, detail="ВМ с таким именем уже существует или создается.")
            
        task = VMTask(
            name=req.name,
            os_type=req.os_type,
            cpu_cores=req.cpu_cores,
            memory_gb=req.memory_gb,
            disk_gb=req.disk_gb,
            custom_image=req.custom_image,
            packages=req.packages,
            network_drives=req.network_drives,
            status="Pending"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # Отправляем в RabbitMQ
        publish_task("vm_tasks", {
            "task_id": task.id,
            "action": "create_vm"
        })
        
        db.close()
        
        # Временно возвращаем те же ключи, чтобы фронт не сломался (пароль будет сгенерирован воркером, 
        # но чтобы не ломать текущий UX фронта, пароль можно будет запрашивать из секрета. 
        # Пока возвращаем статус).
        return {"status": "creating", "name": req.name, "task_id": task.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{name}")
def delete_vm(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.delete_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/start")
def start_vm(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.start_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/stop")
def stop_vm(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.stop_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/restart")
def restart_vm(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.restart_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/metrics")
def get_vm_metrics(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.get_vm_metrics(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- НОВЫЕ МАРШРУТЫ ИЗМЕНЕНИЯ РЕСУРСОВ И БЭКАПОВ ---

@router.post("/{name}/resize")
def resize_vm(name: str, req: VMResizeRequest, client: K8sClient = Depends(get_k8s_client)):
    """Изменение лимитов CPU, RAM и расширение HDD"""
    try:
        # Изменяем CPU/RAM
        client.resize_vm_resources(name, req.cpu_cores, req.memory_gb)
        # Расширяем диск
        client.resize_vm_disk(name, req.disk_gb)
        return {"status": "resized", "name": name, "cpu_cores": req.cpu_cores, "memory_gb": req.memory_gb, "disk_gb": req.disk_gb}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/settings")
def update_vm_settings(name: str, req: VMSettingsUpdateRequest, client: K8sClient = Depends(get_k8s_client)):
    """Обновление настроек ВМ (ресурсы, лимиты диска, проброс портов, фаервол)"""
    from app.db import SessionLocal
    from app.models.models import VMTask
    import json
    
    try:
        db = SessionLocal()
        try:
            db_vm = db.query(VMTask).filter(VMTask.name == name).first()
            if not db_vm:
                raise HTTPException(status_code=404, detail="ВМ не найдена в БД")
                
            # 1. Изменение CPU, RAM и диска в K8s
            if db_vm.cpu_cores != req.cpu_cores or db_vm.memory_gb != req.memory_gb:
                client.resize_vm_resources(name, req.cpu_cores, req.memory_gb)
                db_vm.cpu_cores = req.cpu_cores
                db_vm.memory_gb = req.memory_gb
                
            if db_vm.disk_gb != req.disk_gb:
                client.resize_vm_disk(name, req.disk_gb)
                db_vm.disk_gb = req.disk_gb
                
            # 2. Обновление лимитов диска в БД
            db_vm.disk_read_mbs = req.disk_read_mbs
            db_vm.disk_write_mbs = req.disk_write_mbs
            db_vm.disk_read_iops = req.disk_read_iops
            db_vm.disk_write_iops = req.disk_write_iops
            
            # 3. Обновление портов и фаервола в БД
            ports_list = [p.dict() for p in req.ports_config] if req.ports_config is not None else []
            fw_list = req.firewall_rules if req.firewall_rules is not None else []
            
            db_vm.ports_config = json.dumps(ports_list)
            db_vm.firewall_rules = json.dumps(fw_list)
            db.commit()
            
            # 4. Если ВМ запущена, мгновенно перенастраиваем фаервол/порты
            vm_k8s = client.get_vm(name)
            if vm_k8s.get("status") == "Running" and vm_k8s.get("ips"):
                ip = vm_k8s["ips"][0]
                reconcile_vm_firewall_rules(ip, db_vm.ports_config, db_vm.firewall_rules)
                
            return {"status": "success", "message": "Настройки ВМ сохранены"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error updating VM settings for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/metrics/history")
def get_vm_metrics_history(name: str, range_hours: int = Query(1, ge=1, le=24), client: K8sClient = Depends(get_k8s_client)):
    """Получение истории метрик CPU/RAM из Prometheus за указанный период (в часах)"""
    import time
    
    end_time = int(time.time())
    start_time = end_time - (range_hours * 3600)
    
    # 1. Запрос CPU
    cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{namespace="default",pod=~"virt-launcher-{name}-.*",container="compute"}}[2m])) * 100'
    cpu_data = client.query_prometheus(cpu_query, start_time, end_time, step="30s")
    
    # 2. Запрос RAM
    ram_query = f'container_memory_working_set_bytes{{namespace="default",pod=~"virt-launcher-{name}-.*",container="compute"}}'
    ram_data = client.query_prometheus(ram_query, start_time, end_time, step="30s")
    
    # Форматируем данные для фронтенда
    formatted_points = {}
    
    # Разбираем CPU
    if cpu_data and cpu_data.get("status") == "success":
        results = cpu_data.get("data", {}).get("result", [])
        if results:
            values = results[0].get("values", [])
            for val in values:
                ts = int(float(val[0]))
                ts_aligned = (ts // 30) * 30
                cpu_val = round(float(val[1]), 2)
                formatted_points[ts_aligned] = {"timestamp": ts_aligned, "cpu": cpu_val, "memory_mb": 0.0}
                
    # Разбираем RAM
    if ram_data and ram_data.get("status") == "success":
        results = ram_data.get("data", {}).get("result", [])
        if results:
            values = results[0].get("values", [])
            for val in values:
                ts = int(float(val[0]))
                ts_aligned = (ts // 30) * 30
                ram_bytes = float(val[1])
                ram_mb = round(ram_bytes / (1024 * 1024), 2)
                if ts_aligned in formatted_points:
                    formatted_points[ts_aligned]["memory_mb"] = ram_mb
                else:
                    formatted_points[ts_aligned] = {"timestamp": ts_aligned, "cpu": 0.0, "memory_mb": ram_mb}
                    
    # Превращаем в отсортированный список
    history_list = sorted(formatted_points.values(), key=lambda x: x["timestamp"])
    return history_list

@router.post("/{name}/backup")
def create_backup(name: str, client: K8sClient = Depends(get_k8s_client)):
    """Создать резервную копию VM"""
    try:
        return client.create_vm_backup(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/backups")
def list_backups(name: str, client: K8sClient = Depends(get_k8s_client)):
    """Получить список резервных копий VM"""
    try:
        return client.list_vm_backups(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{name}/backups/{backup_name}")
def delete_backup(name: str, backup_name: str, client: K8sClient = Depends(get_k8s_client)):
    """Удалить резервную копию"""
    try:
        return client.delete_vm_backup(backup_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/restore/{backup_name}")
def restore_vm_backup(name: str, backup_name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.restore_vm_backup(name, backup_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def resolve_vm_ip(ips: list) -> Optional[str]:
    # Ищем мостовой IP (не внутренний k8s под и не внутренний KubeVirt NAT)
    for ip in ips:
        if (
            not ip.startswith("10.244.") and 
            not ip.startswith("10.42.") and 
            not ip.startswith("10.0.2.") and 
            not ip.startswith("127.0.") and 
            ":" not in ip
        ):
            return ip
    # Фолбэк на под-сеть K3s (10.42.x.x / 10.244.x.x), к которой есть доступ с хоста
    for ip in ips:
        if (ip.startswith("10.42.") or ip.startswith("10.244.")) and ":" not in ip:
            return ip
    # Если ничего нет, возвращаем первый IPv4
    for ip in ips:
        if ":" not in ip:
            return ip
    return ips[0] if ips else None


class VMCommandExecuteRequest(BaseModel):
    command: str = Field(..., description="Команда для выполнения на ВМ через SSH")
    cwd: Optional[str] = Field(None, description="Текущая рабочая директория")


@router.get("/{name}/ssh-details")
def get_vm_ssh_details(name: str, client: K8sClient = Depends(get_k8s_client)):
    """Получить детальный статус виртуальной машины через SSH (процессы, systemd, docker)"""
    try:
        vm = client.get_vm(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Виртуальная машина {name} не найдена: {str(e)}")
        
    if vm.get("status") != "Running":
        raise HTTPException(status_code=400, detail="Мониторинг доступен только для запущенных виртуальных машин.")

    ips = vm.get("ips", [])
    external_ip = resolve_vm_ip(ips)

    if not external_ip:
        raise HTTPException(status_code=400, detail="У виртуальной машины нет назначенного IP-адреса. Ожидайте запуска.")

    credentials = vm.get("credentials", {})
    username = credentials.get("username", "root")
    password = credentials.get("password")

    if not password or password == "N/A":
        raise HTTPException(status_code=400, detail="Не найден пароль для подключения к ВМ.")

    inspector = SSHInspector(
        host=external_ip,
        port=22,
        username=username,
        password=password
    )
    metrics = inspector.inspect()
    
    return {
        "name": name,
        "host": external_ip,
        "port": 22,
        "username": username,
        **metrics
    }


@router.post("/{name}/execute")
def execute_vm_ssh_command(name: str, req: VMCommandExecuteRequest, client: K8sClient = Depends(get_k8s_client)):
    """Выполнить bash-команду на виртуальной машине через SSH"""
    try:
        vm = client.get_vm(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Виртуальная машина {name} не найдена: {str(e)}")

    if vm.get("status") != "Running":
        raise HTTPException(status_code=400, detail="Выполнение команд доступно только на запущенных виртуальных машинах.")

    ips = vm.get("ips", [])
    external_ip = resolve_vm_ip(ips)

    if not external_ip:
        raise HTTPException(status_code=400, detail="У виртуальной машины нет назначенного IP-адреса.")

    credentials = vm.get("credentials", {})
    username = credentials.get("username", "root")
    password = credentials.get("password")

    if not password or password == "N/A":
        raise HTTPException(status_code=400, detail="Не найден пароль для подключения к ВМ.")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=external_ip,
            port=22,
            username=username,
            password=password,
            timeout=15
        )
        cwd_dir = req.cwd if req.cwd else "~"
        full_command = f"cd {cwd_dir} && {req.command} ; echo \"__CWD__\" ; pwd"
        
        stdin, stdout, stderr = ssh.exec_command(full_command, timeout=15)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        ssh.close()
        
        new_cwd = cwd_dir
        actual_out = out
        if "__CWD__" in out:
            parts = out.split("__CWD__")
            actual_out = parts[0].rstrip("\r\n").rstrip("\n")
            new_cwd = parts[1].strip()
            
        return {
            "exit_status": exit_status,
            "stdout": actual_out,
            "stderr": err,
            "cwd": new_cwd
        }
    except Exception as e:
        logger.error(f"Ошибка выполнения команды на ВМ {name} ({external_ip}): {e}")
        return {
            "exit_status": -1,
            "stdout": "",
            "stderr": f"Не удалось выполнить команду по SSH на ВМ: {str(e)}",
            "cwd": req.cwd if req.cwd else "~"
        }

@router.post("/{name}/migrate")
async def migrate_vm(name: str, target_server_id: str = Query(...), k8s: K8sClient = Depends(get_k8s_client), db: AsyncSession = Depends(get_db)):
    from app.models.models import ExternalServer
    from sqlalchemy import select
    import asyncio
    import base64
    import paramiko
    import uuid
    import random
    import subprocess
    
    # 1. Получаем внешний сервер асинхронно
    res = await db.execute(select(ExternalServer).filter_by(id=target_server_id))
    target_server = res.scalars().first()
    
    if not target_server:
        raise HTTPException(status_code=404, detail="Внешний сервер не найден")
        
    # Блокирующая часть выносится в отдельный поток, чтобы не завешивать event loop FastAPI
    def blocking_migration_task():
        # 2. Получаем ВМ
        vms = k8s.list_vms()
        vm = next((v for v in vms if v["name"] == name), None)
        if not vm:
            raise Exception("Виртуальная машина не найдена")
            
        # Учетные данные
        try:
            secret = k8s.core_api.read_namespaced_secret(f"vm-{name}-auth", "default")
            vm_user = base64.b64decode(secret.data.get("username", b"")).decode("utf-8") if secret.data.get("username") else "root"
            vm_pass = base64.b64decode(secret.data.get("password", b"")).decode("utf-8") if secret.data.get("password") else ""
        except:
            vm_user = "root"
            vm_pass = ""

        # 3. Находим путь к диску
        try:
            pvc = k8s.core_api.read_namespaced_persistent_volume_claim(f"default-disk-{name}", "default")
            pv_name = pvc.spec.volume_name
            pv = k8s.core_api.read_persistent_volume(pv_name)
            
            host_path = pv.spec.local.path if pv.spec.local else None
            if not host_path and pv.spec.host_path:
                host_path = pv.spec.host_path.path
                
            if not host_path:
                raise Exception("Не удалось определить host_path для диска.")
                
            disk_path = f"{host_path}/disk.img"
        except Exception as e:
            raise Exception(f"Ошибка поиска диска: {e}")

        # 4. Останавливаем ВМ
        k8s.stop_vm(name)
        
        # 5. Подключаемся
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                target_server.host, 
                port=target_server.port, 
                username=target_server.username, 
                password=target_server.password,
                timeout=10
            )
            
            ssh.exec_command("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-system-x86 qemu-utils")
            ssh.exec_command(f"mkdir -p /opt/antigravity/vms/{name}")
            
            # 6. Ключ для SCP
            key_path = f"/tmp/mig_key_{uuid.uuid4().hex}"
            nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid"]
            
            subprocess.run(nsenter_prefix + ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_path], check=True)
            pub_key_res = subprocess.run(nsenter_prefix + ["cat", f"{key_path}.pub"], capture_output=True, text=True)
            pub_key = pub_key_res.stdout.strip()
            
            ssh.exec_command(f"mkdir -p ~/.ssh && echo '{pub_key}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")
            
            # 7. SCP
            scp_cmd = f"scp -o StrictHostKeyChecking=no -i {key_path} {disk_path} {target_server.username}@{target_server.host}:/opt/antigravity/vms/{name}/disk.img"
            scp_res = subprocess.run(nsenter_prefix + ["sh", "-c", scp_cmd], capture_output=True, text=True)
            
            subprocess.run(nsenter_prefix + ["rm", "-f", key_path, f"{key_path}.pub"])
            
            if scp_res.returncode != 0:
                raise Exception(f"SCP failed: {scp_res.stderr}")
                
            # 8. Service
            ext_ssh_port = random.randint(22000, 30000)
            ram_mb = 2048
            cpu_cores = 2
            try:
                vmi_info = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", name)
                memory_str = vmi_info.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}).get("resources", {}).get("requests", {}).get("memory", "2G")
                if "G" in memory_str:
                    ram_mb = int(memory_str.replace("G", "")) * 1024
                elif "M" in memory_str:
                    ram_mb = int(memory_str.replace("M", ""))
                    
                cpu_cores = vmi_info.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}).get("cpu", {}).get("cores", 2)
            except:
                pass
                
            service_content = f"""[Unit]
Description=Migrated VM {name}
After=network.target

[Service]
ExecStart=/usr/bin/qemu-system-x86_64 -enable-kvm -m {ram_mb} -smp {cpu_cores} -drive file=/opt/antigravity/vms/{name}/disk.img,format=raw,if=virtio -net nic,model=virtio -net user,hostfwd=tcp::{ext_ssh_port}-:22 -nographic
Restart=always

[Install]
WantedBy=multi-user.target
"""
            stdin, stdout, stderr = ssh.exec_command(f"cat << 'EOF' > /etc/systemd/system/vm-{name}.service\n{service_content}\nEOF")
            stdout.channel.recv_exit_status()
            
            ssh.exec_command("systemctl daemon-reload")
            ssh.exec_command(f"systemctl enable --now vm-{name}.service")
            
        except Exception as e:
            raise Exception(f"Ошибка миграции SSH/SCP: {e}")
        finally:
            ssh.close()
            
        # 9. Удаляем ВМ
        try:
            k8s.delete_vm(name)
        except:
            pass
            
        return vm_user, vm_pass, ext_ssh_port

    # Выполняем длительную блокирующую операцию в пуле потоков
    try:
        vm_user, vm_pass, ext_ssh_port = await asyncio.to_thread(blocking_migration_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # 10. Сохраняем результат
    new_id = str(uuid.uuid4())[:8]
    new_server = ExternalServer(
        id=new_id,
        name=f"{name} (Migrated)",
        host=target_server.host,
        port=ext_ssh_port,
        username=vm_user,
        password=vm_pass
    )
    db.add(new_server)
    await db.commit()
    
    return {"status": "success", "message": f"ВМ {name} успешно мигрирована", "new_server_id": new_server.id}
