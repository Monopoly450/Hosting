import os
import re
import paramiko
import secrets
import string
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.core.k8s_client import K8sClient
from app.services.ssh_inspector import SSHInspector

router = APIRouter()
logger = logging.getLogger("app.api.vms")

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

class VMResizeRequest(BaseModel):
    cpu_cores: int = Field(..., ge=1, le=16)
    memory_gb: int = Field(..., ge=1, le=64)
    disk_gb: int = Field(..., ge=10, le=500)

def generate_random_password(length=12) -> str:
    """Генерирует криптографически стойкий случайный пароль"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

# Базовые константы-шаблоны для генерации манифестов
DEFAULT_WINDOWS_ISO = "https://software-static.download.prss.microsoft.com/sg/download/details.aspx?uuid=5e4c6052-b13c-4384-9ff5-c439162e08e7"
DEFAULT_UBUNTU_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"

def generate_ubuntu_manifest(req: VMCreationRequest, password: str) -> dict:
    # Если выбран кастомный образ, загружаем его из локального хранилища бэкенда
    image_url = DEFAULT_UBUNTU_IMAGE
    if req.os_type == "custom" and req.custom_image:
        # K3s нода обращается к бэкенду на localhost:8000
        image_url = f"http://127.0.0.1:8000/static/images/{req.custom_image}"
        
    return {
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
                                    "name": "bridge-net",
                                    "bridge": {}
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
                            "name": "bridge-net",
                            "multus": {
                                "networkName": "bridge-network"
                            }
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
                                "userData": f"#cloud-config\nssh_pwauth: True\ndisable_root: false\nchpasswd:\n  list: |\n    root:{password}\n    ubuntu:{password}\n  expire: False\nusers:\n  - name: root\n    lock_passwd: false\n  - name: ubuntu\n    sudo: ['ALL=(ALL) NOPASSWD:ALL']\n    shell: /bin/bash\n    lock_passwd: false\nruncmd:\n  - echo \"root:{password}\" | chpasswd\n  - echo \"ubuntu:{password}\" | chpasswd\n  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config\n  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config\n  - sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config.d/*.conf || true\n  - systemctl restart ssh || systemctl restart sshd\n  - while ! ping -c 1 -W 2 security.ubuntu.com >/dev/null 2>&1; do sleep 2; done\n  - i=1; while [ $i -le 50 ]; do apt-get update && apt-get install -y qemu-guest-agent && break || sleep 5; i=$((i+1)); done\n  - systemctl enable --now qemu-guest-agent\n"
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

def generate_windows_manifest(req: VMCreationRequest) -> dict:
    iso_url = req.iso_url or DEFAULT_WINDOWS_ISO
    # Если Windows создается из кастомного образа ISO
    if req.os_type == "custom" and req.custom_image:
        iso_url = f"http://127.0.0.1:8000/static/images/{req.custom_image}"

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
                                    "disk": {
                                        "bus": "virtio"
                                    }
                                },
                                {
                                    "name": "winiso",
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
                                    "name": "bridge-net",
                                    "bridge": {}
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
                            "name": "bridge-net",
                            "multus": {
                                "networkName": "bridge-network"
                            }
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
                                "image": "quay.io/kubevirt/virtio-container-disk"
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

@router.get("/{name}", response_model=dict)
def get_vm_details(name: str, client: K8sClient = Depends(get_k8s_client)):
    try:
        return client.get_vm(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Виртуальная машина {name} не найдена: {e}")

@router.post("", status_code=status.HTTP_201_CREATED)
def create_vm(req: VMCreationRequest, client: K8sClient = Depends(get_k8s_client)):
    try:
        # Генерируем случайный пароль для рута
        generated_password = generate_random_password()
        
        # Определяем стандартный логин
        username = "root"
        if req.os_type == "ubuntu":
            username = "ubuntu"
        elif req.os_type == "windows":
            username = "Administrator"
            
        # Windows устанавливается из ISO в ручном режиме, но пароль все равно генерируем
        # Ubuntu и кастомные образы дисков (если поддерживают cloud-init) настраиваем через cloud-init
        if req.os_type in ["ubuntu", "custom"]:
            manifest = generate_ubuntu_manifest(req, generated_password)
        elif req.os_type == "windows":
            manifest = generate_windows_manifest(req)
        else:
            raise HTTPException(status_code=400, detail="Неверный тип ОС.")
            
        # 1. Создаем VM
        client.create_vm_from_manifest(manifest)
        
        # 2. Сохраняем пароль в Kubernetes Secrets
        client.create_credentials_secret(req.name, username, generated_password)
        
        return {"status": "creating", "name": req.name, "username": username, "password": generated_password}
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
