from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
import os
import json
import re
import paramiko
import secrets
import string
import hashlib

def generate_mac_address(name: str) -> str:
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    # 02:00:00 prefix ensures it's a locally administered unicast MAC
    return f"02:00:00:{h[0:2]}:{h[2:4]}:{h[4:6]}"


def compute_static_ip(vm_id: int) -> str:
    """Детерминированный стабильный IP на мосту br-vms (172.20.0.0/24).
    Диапазон .30-.229 — не пересекается со шлюзом .1."""
    return f"172.20.0.{30 + (int(vm_id) % 200)}"

import logging
from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from app.core.k8s_client import K8sClient
from app.services.ssh_inspector import SSHInspector
from app.core.auth import get_current_user, check_admin
from app.models.models import User
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger("app.api.vms")

def check_vm_ownership(vm_name: str, current_user: User, need: str = "editor"):
    """Проверяет права доступа к ВМ: админ, владелец или участник проекта.

    По умолчанию требуется роль editor (безопасно для изменяющих операций);
    у эндпоинтов только на чтение передаём need="viewer".
    """
    if current_user.role == "admin":
        return
    from app.db import SessionLocal
    from app.models.models import VMTask
    from app.core.rbac import can_access
    db = SessionLocal()
    try:
        vm = db.query(VMTask).filter(VMTask.name == vm_name).first()
        if not vm or not can_access(db, current_user, vm.owner_id, vm.project_id, need):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ запрещен: Вы не являетесь владельцем этой виртуальной машины."
            )
    finally:
        db.close()

def get_host_ip() -> str:
    """Определяет IP хоста, доступный для подов K3s"""
    from app.core.netutils import detect_host_ip
    return detect_host_ip()

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
    cloud_init_template: Optional[str] = Field(None, description="Предустановленный шаблон (lamp, docker, nodejs, wordpress)")
    custom_user_data: Optional[str] = Field(None, description="Собственный cloud-init userdata")
    ssh_key: Optional[str] = Field(None, description="Публичный SSH-ключ для беспарольного входа")

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
DEFAULT_PROXMOX_ISO = "https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1.iso"
DEFAULT_TRUENAS_ISO = "https://download.truenas.com/TrueNAS-SCALE-Dragonfish/24.04.2.5/TrueNAS-SCALE-24.04.2.5.iso"

# Типы ОС, которые ставятся с ISO (пустой диск + загрузка установщика), а не из cloud-образа
ISO_INSTALL_OS = ("windows", "proxmox", "truenas")

# Централизованная карта Linux-образов: os_type -> (URL облачного образа, логин по умолчанию).
# Все образы поддерживают cloud-init (пароль/сеть настраиваются автоматически).
LINUX_CLOUD_IMAGES = {
    "ubuntu":    (DEFAULT_UBUNTU_IMAGE, "ubuntu"),
    "debian":    (DEFAULT_DEBIAN_IMAGE, "debian"),
    "centos":    (DEFAULT_CENTOS_IMAGE, "cloud-user"),
    "bitrix":    (DEFAULT_CENTOS_IMAGE, "cloud-user"),
    "almalinux": ("https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2", "almalinux"),
    "rocky":     ("https://download.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2", "rocky"),
    "fedora":    ("https://download.fedoraproject.org/pub/fedora/linux/releases/41/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-41-1.4.x86_64.qcow2", "fedora"),
    "opensuse":  ("https://download.opensuse.org/repositories/Cloud:/Images:/Leap_15.6/images/openSUSE-Leap-15.6.x86_64-NoCloud.qcow2", "opensuse"),
    "arch":      ("https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2", "arch"),
    "alpine":    ("https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/cloud/generic_alpine-3.21.3-x86_64-bios-cloudinit-r0.qcow2", "alpine"),
}


def default_user_for(os_type: str) -> str:
    """Логин по умолчанию для облачного образа данной ОС."""
    return LINUX_CLOUD_IMAGES.get(os_type, (None, "ubuntu"))[1]


def generate_linux_manifest(req: VMCreationRequest, password: str) -> dict:
    # Определение базового образа и логина (из централизованной карты)
    access_mode = "ReadWriteMany" if "nfs" in settings.STORAGE_CLASS.lower() else "ReadWriteOnce"
    default_image, default_user = LINUX_CLOUD_IMAGES.get(req.os_type, (DEFAULT_UBUNTU_IMAGE, "ubuntu"))
    image_url = req.iso_url or default_image

    # Пакеты и команды шаблона окружения — под конкретное семейство ОС.
    # Раньше здесь были захардкожены дебиановские имена (apache2, docker.io,
    # redis-server) для ВСЕХ систем, поэтому на RHEL-семействе и прочих
    # установка падала и шаблон молча не применялся.
    from app.services.os_profiles import build_template_steps, nfs_client_package
    template_packages, template_commands = build_template_steps(req.cloud_init_template, req.os_type)

    # Обработка пакетов
    packages_yaml = ""
    all_packages = []
    if req.packages:
        all_packages.extend([p.strip() for p in req.packages.split(",") if p.strip()])
    all_packages.extend(template_packages)
    if all_packages:
        packages_yaml = "\npackages:\n" + "\n".join([f"  - {p}" for p in all_packages])
            
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
            # nfs-common — дебиановское имя; в RHEL пакет называется nfs-utils,
            # в openSUSE — nfs-client. Без правильного имени монтирование
            # сетевого диска на не-Debian системах не работало.
            nfs_pkg = nfs_client_package(req.os_type)
            if nfs_pkg not in packages_yaml:
                if packages_yaml:
                    packages_yaml += f"\n  - {nfs_pkg}"
                else:
                    packages_yaml = f"\npackages:\n  - {nfs_pkg}"

    # Специфично для Bitrix
    runcmd_yaml = ""
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            if packages_yaml:
                packages_yaml += "\n  - wget"
            else:
                packages_yaml = "\npackages:\n  - wget"
        runcmd_yaml = "\n  - wget http://repos.1c-bitrix.ru/yum/bitrix-env.sh\n  - chmod +x bitrix-env.sh\n  - ./bitrix-env.sh -s -p -H " + req.name + "\n"

    # Дополнительные команды шаблона
    if template_commands:
        runcmd_yaml += "\n" + "\n".join([f"  - {cmd}" for cmd in template_commands])

    ssh_pwauth_val = "True"
    users_yaml = "users:\n  - default"
    ssh_enable_commands = """  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
  - sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config.d/*.conf || true
  - echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config || true"""
  
    if getattr(req, "ssh_key", None):
        ssh_pwauth_val = "False"
        users_yaml = f"""users:
  - default
  - name: root
    ssh_authorized_keys:
      - {req.ssh_key}
  - name: {default_user}
    ssh_authorized_keys:
      - {req.ssh_key}"""
        ssh_enable_commands = """  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config || true
  - sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/g' /etc/ssh/sshd_config.d/*.conf || true"""

    # Автологин в консоли — через drop-in для systemd-юнита getty. В системах
    # без systemd (Alpine с OpenRC) этот файл никто не прочитает, а команды
    # systemctl только зашумят лог ошибками, поэтому там их просто нет.
    from app.services.cloudinit import GUEST_AGENT_RETRY_RUNCMD
    from app.services.os_profiles import has_systemd
    if has_systemd(req.os_type):
        autologin_yaml = f"""
write_files:
  - path: /etc/systemd/system/getty@tty1.service.d/override.conf
    content: |
      [Service]
      ExecStart=
      ExecStart=-/sbin/agetty --autologin {default_user} --noclear %I $TERM"""
        autologin_runcmd = """
  - systemctl daemon-reload || true
  - systemctl restart getty@tty1.service || true"""
        restart_ssh_cmd = "  - systemctl restart ssh || systemctl restart sshd || true"
    else:
        autologin_yaml = ""
        autologin_runcmd = ""
        restart_ssh_cmd = "  - rc-service sshd restart || true"

    # --- Полностью стабильный IP (не меняется при перезагрузке) ---
    # К pod-интерфейсу (masquerade, интернет) добавляем второй bridge-интерфейс
    # с ФИКСИРОВАННЫМ MAC и СТАТИЧЕСКИМ IP, прописанным в госте через cloud-init.
    #  - ВМ в кластере -> статический IP в сети кластера (192.168.100.x, изоляция).
    #  - Обычная локальная ВМ -> статический IP на мосту br-vms (172.20.0.x).
    static_ip = getattr(req, "static_ip", None)
    cluster_network = getattr(req, "cluster_network", None)
    pod_mac = generate_mac_address(req.name)
    lan_mac = generate_mac_address(req.name + "-lan")

    from app.services.cloudinit import build_network_data
    if static_ip:
        network_data = build_network_data(pod_mac, lan_mac, static_ip)
        if cluster_network:
            extra_interface = {"name": "clusternet", "bridge": {}, "macAddress": lan_mac}
            extra_network = {"name": "clusternet", "multus": {"networkName": cluster_network}}
        else:
            extra_interface = {"name": "lan", "bridge": {}, "macAddress": lan_mac}
            extra_network = {"name": "lan", "multus": {"networkName": "bridge-network"}}
    else:
        # Один pod-интерфейс: матчим по его MAC, а не по маске имени "e*" —
        # имена интерфейсов различаются между дистрибутивами (eth0/ens3/enp1s0),
        # а MAC мы задаём сами в манифесте.
        network_data = f"""version: 2
ethernets:
  pod-nic:
    match:
      macaddress: "{pod_mac}"
    dhcp4: true
"""
        extra_interface = None
        extra_network = None

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
                            "cores": req.cpu_cores,
                            "model": "host-passthrough"
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
                                    "cache": "writeback",
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
                                    "masquerade": {},
                                    # Стабильный MAC (детерминирован от имени) — не меняется при перезагрузке
                                    "macAddress": generate_mac_address(req.name)
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
                                "userData": req.custom_user_data if req.custom_user_data else f"""#cloud-config
ssh_pwauth: {ssh_pwauth_val}
disable_root: false
chpasswd:
  list: |
    root:{password}
    {default_user}:{password}
  expire: False
{users_yaml}
{packages_yaml}{mounts_yaml}{autologin_yaml}
runcmd:
  - echo "root:{password}" | chpasswd
  - echo "{default_user}:{password}" | chpasswd
  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
{ssh_enable_commands}
{restart_ssh_cmd}{autologin_runcmd}
  - while ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; do sleep 2; done
{GUEST_AGENT_RETRY_RUNCMD}{runcmd_yaml}
""",
                                # Сеть отдаём отдельным документом network-config, а не файлом
                                # netplan внутри write_files: netplan есть только в Ubuntu, а
                                # cloud-init рендерит networkData в нативный формат каждой
                                # системы (NetworkManager, /etc/network/interfaces, networkd).
                                "networkData": network_data,
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
                            "storageClassName": settings.STORAGE_CLASS,
                            "accessModes": [
                                access_mode
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

    # Инжектим bridge-интерфейс на br-vms для стабильного статического IP
    if extra_interface and extra_network:
        manifest["spec"]["template"]["spec"]["domain"]["devices"]["interfaces"].append(extra_interface)
        manifest["spec"]["template"]["spec"]["networks"].append(extra_network)

    return manifest

def generate_windows_manifest(req: VMCreationRequest) -> dict:
    # У каждой ISO-ОС свой установочный образ
    if req.os_type == "proxmox":
        iso_url = req.iso_url or DEFAULT_PROXMOX_ISO
    elif req.os_type == "truenas":
        iso_url = req.iso_url or DEFAULT_TRUENAS_ISO
    else:
        iso_url = req.iso_url or DEFAULT_WINDOWS_ISO
    # Если ОС создаётся из кастомного загруженного ISO
    if req.os_type == "custom" and req.custom_image:
        host_ip = get_host_ip()
        iso_url = f"http://{host_ip}:8000/static/images/{req.custom_image}"

    access_mode = "ReadWriteMany" if "nfs" in settings.STORAGE_CLASS.lower() else "ReadWriteOnce"

    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": req.name,
            "namespace": "default",
            "labels": {
                # Метка отражает реальный тип ОС (windows или proxmox), а не всегда "windows"
                "hosting.antigravity.io/template": req.os_type if req.os_type in ISO_INSTALL_OS else "windows",
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
                            "cores": req.cpu_cores,
                            "model": "host-passthrough"
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
                                    "cache": "writeback",
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
                                    "masquerade": {},
                                    # Стабильный MAC (детерминирован от имени) — не меняется при перезагрузке
                                    "macAddress": generate_mac_address(req.name)
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
                            "storageClassName": settings.STORAGE_CLASS,
                            "accessModes": [
                                access_mode
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
                            "storageClassName": settings.STORAGE_CLASS,
                            "accessModes": [
                                access_mode
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
def list_vms(client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    try:
        all_vms = client.list_vms()
        from app.db import SessionLocal
        from app.models.models import VMTask, User
        db = SessionLocal()
        try:
            if current_user.role == "admin":
                db_vms = db.query(VMTask).all()
                db_users = db.query(User).all()
                user_map = {u.id: u.username for u in db_users}
                
                db_vm_map = {vm.name: vm.id for vm in db_vms}
                db_vm_owner_map = {vm.name: user_map.get(vm.owner_id, "Unknown") for vm in db_vms}
                for vm in all_vms:
                    name = vm.get("name")
                    vm["id"] = db_vm_map.get(name)
                    vm["owner_username"] = db_vm_owner_map.get(name, "Unknown")
                return all_vms
            else:
                # Видны свои ВМ и ВМ проектов, где пользователь состоит
                from sqlalchemy import or_
                from app.core.rbac import visible_project_ids
                conds = [VMTask.owner_id == current_user.id]
                pids = visible_project_ids(db, current_user)
                if pids:
                    conds.append(VMTask.project_id.in_(pids))
                db_vms = db.query(VMTask).filter(or_(*conds)).all()

                users_map = {u.id: u.username for u in db.query(User).all()}
                db_vm_map = {vm.name: vm for vm in db_vms}
                filtered_vms = []
                for vm in all_vms:
                    name = vm.get("name")
                    row = db_vm_map.get(name)
                    if row:
                        vm["id"] = row.id
                        vm["owner_username"] = users_map.get(row.owner_id, current_user.username)
                        filtered_vms.append(vm)
                return filtered_vms
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _ip_in_rule(vm_ip: str, line: str) -> bool:
    """True, если vm_ip встречается в строке правила как целый адрес, а не как
    случайная подстрока чужого адреса.

    Голое `vm_ip in line` совпадало и с правилом для 172.20.0.130, когда
    чистили 172.20.0.13 — тот же самый первый октет+сегмент, третий адрес
    внутри четвёртого. На каждой смене IP какой-нибудь ВМ это могло стереть
    DNAT/FORWARD правило совершенно другой, ни при чём не бывшей машины —
    после чего у неё переставали открываться сайты и падал доступ по SSH,
    хотя её собственный IP не менялся вовсе."""
    import re
    return re.search(rf"(?<!\d){re.escape(vm_ip)}(?!\d)", line) is not None


def clear_iptables_rules_for_ip(vm_ip: str):
    import subprocess
    nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]

    # Clear PREROUTING rules
    res = subprocess.run(nsenter_prefix + ["iptables -t nat -S PREROUTING"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if _ip_in_rule(vm_ip, line):
                del_cmd = line.replace("-A ", "-D ")
                subprocess.run(nsenter_prefix + [f"iptables -t nat {del_cmd}"], capture_output=True, timeout=5)

    # Clear FORWARD rules
    res = subprocess.run(nsenter_prefix + ["iptables -S FORWARD"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if _ip_in_rule(vm_ip, line):
                del_cmd = line.replace("-A ", "-D ")
                subprocess.run(nsenter_prefix + [f"iptables {del_cmd}"], capture_output=True, timeout=5)

def clear_iptables_rules_for_port(ext_port: int):
    import subprocess
    nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
    res = subprocess.run(nsenter_prefix + ["iptables -t nat -S PREROUTING"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if f"--dport {ext_port} " in line or line.endswith(f"--dport {ext_port}"):
                del_cmd = line.replace("-A ", "-D ")
                subprocess.run(nsenter_prefix + [f"iptables -t nat {del_cmd}"], capture_output=True, timeout=5)

def reconcile_vm_firewall_rules(vm_ip: str, vm_id: Optional[int] = None, ports_config: str = None, firewall_rules: str = None, os_type: str = "linux", old_ip: Optional[str] = None):
    """Настраивает проброс портов и правила доступа для ВМ с помощью iptables на хосте.

    old_ip — прежний адрес этой же ВМ, если он изменился (перезагрузка сменила
    pod IP, DHCP выдал новую аренду и т.п.). Правила DNAT по номеру порта и так
    переустанавливаются (clear_iptables_rules_for_port ниже), а вот FORWARD
    ACCEPT/DROP для СТАРОГО IP без этого никогда не удалялись: они привязаны к
    адресу, а не к порту. IP-адреса переиспользуются (и статический пул, и
    pod-сеть), поэтому со временем чужая ВМ могла получить ранее занятый адрес
    и унаследовать чужое правило FORWARD — вплоть до DROP, если у прежнего
    владельца был белый список."""
    import subprocess
    import json
    try:
        nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
        
        # Автонастройка хостового шлюза для существующих кластерных сетей
        if vm_id:
            try:
                from app.db import SessionLocal
                from app.models.models import VMTask, Cluster
                db = SessionLocal()
                try:
                    db_vm = db.query(VMTask).filter(VMTask.id == vm_id).first()
                    if db_vm and db_vm.cluster_id:
                        cluster = db.query(Cluster).filter(Cluster.id == db_vm.cluster_id).first()
                        if cluster and cluster.network_name:
                            bridge_name = "br-" + cluster.network_name[:11]
                            
                            # Проверяем и настраиваем IP на мосту хоста
                            create_br = f"ip link show {bridge_name} || (ip link add {bridge_name} type bridge && ip link set {bridge_name} up)"
                            subprocess.run(nsenter_prefix + [create_br], capture_output=True, timeout=5)
                            
                            # 1. Удаляем конфликтный IP 192.168.100.1 со всех других мостов
                            get_conflict_devs = "ip -o addr show | grep 192.168.100.1"
                            res_devs = subprocess.run(nsenter_prefix + [get_conflict_devs], capture_output=True, text=True, timeout=5)
                            if res_devs.returncode == 0:
                                for line in res_devs.stdout.splitlines():
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        dev = parts[1].strip()
                                        if dev and dev != bridge_name:
                                            del_ip_cmd = f"ip addr del 192.168.100.1/24 dev {dev}"
                                            subprocess.run(nsenter_prefix + [del_ip_cmd], capture_output=True, timeout=5)
                                            logger.info(f"Удален конфликтный IP 192.168.100.1 с неактивного моста {dev}")
                            
                            # 2. Назначаем IP 192.168.100.1/24 на наш активный мост
                            add_ip = f"ip addr show dev {bridge_name} | grep 192.168.100.1 || ip addr add 192.168.100.1/24 dev {bridge_name}"
                            subprocess.run(nsenter_prefix + [add_ip], capture_output=True, timeout=5)
                            logger.info(f"Сверка моста кластера: настроен хостовый шлюз 192.168.100.1/24 для моста {bridge_name} (ВМ: {db_vm.name})")
                finally:
                    db.close()
            except Exception as bridge_err:
                logger.error(f"Не удалось автонастроить хостовый IP для кластерного моста {vm_id}: {bridge_err}")

        # Очищаем старые правила по IP (текущему и, если он менялся, прежнему —
        # см. пояснение про old_ip в docstring выше)
        clear_iptables_rules_for_ip(vm_ip)
        if old_ip and old_ip != vm_ip:
            clear_iptables_rules_for_ip(old_ip)

        # Парсим список портов
        ports = []
        if ports_config:
            try:
                ports = json.loads(ports_config)
            except Exception as e:
                logger.error(f"Error parsing ports_config: {e}")
                
        # Если порты не настроены, используем дефолтные
        if not ports:
            if vm_id:
                if os_type == "windows":
                    ports = [
                        {"ext_port": 33000 + vm_id, "int_port": 3389, "name": "RDP"},
                        {"ext_port": 22000 + vm_id, "int_port": 22, "name": "SSH"},
                        {"ext_port": 28000 + vm_id, "int_port": 80, "name": "HTTP"}
                    ]
                else:
                    ports = [
                        {"ext_port": 22000 + vm_id, "int_port": 22, "name": "SSH"},
                        {"ext_port": 28000 + vm_id, "int_port": 80, "name": "HTTP"},
                        {"ext_port": 44300 + vm_id, "int_port": 443, "name": "HTTPS"}
                    ]
            else:
                last_octet = int(vm_ip.split('.')[-1])
                if os_type == "windows":
                    ports = [
                        {"ext_port": 33000 + last_octet, "int_port": 3389, "name": "RDP"},
                        {"ext_port": 22000 + last_octet, "int_port": 22, "name": "SSH"},
                        {"ext_port": 28000 + last_octet, "int_port": 80, "name": "HTTP"}
                    ]
                else:
                    ports = [
                        {"ext_port": 22000 + last_octet, "int_port": 22, "name": "SSH"},
                        {"ext_port": 28000 + last_octet, "int_port": 80, "name": "HTTP"},
                        {"ext_port": 44300 + last_octet, "int_port": 443, "name": "HTTPS"}
                    ]

        # Очищаем старые правила DNAT для каждого из портов, чтобы они не указывали на прошлые IP-адреса
        for p in ports:
            ext_port = p.get("ext_port")
            if ext_port:
                clear_iptables_rules_for_port(int(ext_port))
            
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
                
        # ЗАЩИТА ОТ ИНЪЕКЦИИ: vm_ip подставляется в shell-команду iptables,
        # поэтому он обязан быть валидным IPv4. Иначе — не трогаем файрвол.
        from app.core.netutils import is_valid_ipv4, is_valid_ip_or_cidr
        if not is_valid_ipv4(vm_ip):
            logger.error(f"reconcile_vm_firewall_rules: некорректный vm_ip {vm_ip!r}, пропуск")
            return

        # Применяем правила для каждого порта
        for p in ports:
            ext_port = int(p.get("ext_port"))
            int_port = int(p.get("int_port"))

            # 1. Добавляем DNAT правило в PREROUTING
            add_dnat = f"iptables -t nat -A PREROUTING -p tcp --dport {ext_port} -j DNAT --to-destination {vm_ip}:{int_port}"
            subprocess.run(nsenter_prefix + [add_dnat], capture_output=True, timeout=5)

            # 2. Получаем белый список IP для этого порта.
            #    Отбрасываем всё, что не является валидным IP/CIDR — значения
            #    из firewall_rules задаёт пользователь и они уходят в iptables.
            whitelist = fw_map.get(int_port) or fw_map.get(ext_port) or []
            whitelist = [ip.strip() for ip in whitelist if ip and ip.strip()]
            allow_all = (not whitelist) or ("0.0.0.0/0" in whitelist)
            safe_whitelist = [ip for ip in whitelist if is_valid_ip_or_cidr(ip)]
            for bad in [ip for ip in whitelist if ip not in safe_whitelist and ip != "0.0.0.0/0"]:
                logger.warning(f"reconcile_vm_firewall_rules: игнорирую некорректный IP в белом списке: {bad!r}")

            # Если белый список пуст или содержит 0.0.0.0/0, разрешаем всем
            if allow_all:
                add_forward = f"iptables -A FORWARD -p tcp -d {vm_ip} --dport {int_port} -j ACCEPT"
                subprocess.run(nsenter_prefix + [add_forward], capture_output=True, timeout=5)
            else:
                # Разрешаем доступ только для проверенного белого списка
                for ip_addr in safe_whitelist:
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

@router.get("/os-catalog")
def get_os_catalog(current_user: User = Depends(get_current_user)):
    """Список ОС и совместимых с каждой шаблонов окружения.

    Нужен интерфейсу, чтобы не предлагать шаблон, который для выбранной
    системы всё равно не соберётся: набор пакетов у семейств разный, и часть
    шаблонов описана не для всех (см. app.services.os_profiles).
    """
    from app.services.os_profiles import TEMPLATES, supported_templates_for

    return {
        "templates": [{"value": name, "label": spec["label"]} for name, spec in TEMPLATES.items()],
        # os_type -> список value шаблонов, применимых к этой ОС
        "supported": {os_type: supported_templates_for(os_type) for os_type in LINUX_CLOUD_IMAGES},
        # ОС, которые ставятся с ISO — у них cloud-init нет вообще
        "iso_install": list(ISO_INSTALL_OS),
    }


@router.get("/balancer/resources", response_model=List[dict])
def get_balancer_resources(client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
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
            
            # RAM limit
            ram_val_raw = vm.get("memory_gb") or vm.get("memory") or 2
            if isinstance(ram_val_raw, str):
                match = re.match(r'^([\d\.]+)\s*([A-Za-z]*)$', ram_val_raw.strip())
                if match:
                    val = float(match.group(1))
                    suffix = match.group(2).upper()
                    if suffix in ("GI", "G"):
                        ram_limit_gb = val
                    elif suffix in ("MI", "M"):
                        ram_limit_gb = val / 1024.0
                    elif suffix in ("KI", "K"):
                        ram_limit_gb = val / (1024.0 * 1024.0)
                    elif suffix in ("TI", "T"):
                        ram_limit_gb = val * 1024.0
                    else:
                        ram_limit_gb = val
                else:
                    try:
                        ram_limit_gb = float(ram_val_raw)
                    except ValueError:
                        ram_limit_gb = 2.0
            else:
                ram_limit_gb = float(ram_val_raw)
            ram_limit_mb = ram_limit_gb * 1024
            cpu_limit = float(vm.get("cpu_cores", 2))
            
            cpu_percent = round((cpu_val / cpu_limit) * 100, 1) if cpu_limit > 0 else 0.0
            ram_usage_mb = round(ram_val / (1024 * 1024), 1)
            ram_percent = round((ram_usage_mb / ram_limit_mb) * 100, 1) if ram_limit_mb > 0 else 0.0
            
            balancer_stats.append({
                "vm_name": vm_name,
                "pod_name": pod_name or f"virt-launcher-{vm_name}",
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
def get_vm_details(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user, need="viewer")
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
                    reconcile_vm_firewall_rules(ip, db_vm.id, db_vm.ports_config, db_vm.firewall_rules, db_vm.os_type)
        finally:
            db.close()
            
        # Получаем данные о текущей скорости диска из Prometheus
        try:
            # Сначала пытаемся получить KubeVirt-специфичные метрики, затем cAdvisor-метрики
            read_speed_query = f'sum(rate(kubevirt_vmi_storage_read_traffic_bytes_total{{name=~"{name}"}}[2m])) or sum(rate(container_fs_reads_bytes_total{{container="compute",pod=~"virt-launcher-{name}-.*"}}[2m]))'
            write_speed_query = f'sum(rate(kubevirt_vmi_storage_write_traffic_bytes_total{{name=~"{name}"}}[2m])) or sum(rate(container_fs_writes_bytes_total{{container="compute",pod=~"virt-launcher-{name}-.*"}}[2m]))'
            read_iops_query = f'sum(rate(kubevirt_vmi_storage_read_iops_total{{name=~"{name}"}}[2m])) or sum(rate(container_fs_reads_total{{container="compute",pod=~"virt-launcher-{name}-.*"}}[2m]))'
            write_iops_query = f'sum(rate(kubevirt_vmi_storage_write_iops_total{{name=~"{name}"}}[2m])) or sum(rate(container_fs_writes_total{{container="compute",pod=~"virt-launcher-{name}-.*"}}[2m]))'
            
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
def create_vm(req: VMCreationRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    try:
        from app.db import SessionLocal
        from app.models.models import VMTask
        from app.queue_client import publish_task

        # Свой cloud-init полностью заменяет сгенерированный, поэтому SSH-ключ
        # в него не попадёт. Не «съедаем» ключ молча — сообщаем об этом явно.
        if getattr(req, "custom_user_data", None) and getattr(req, "ssh_key", None):
            raise HTTPException(
                status_code=400,
                detail="Свой Cloud-Init скрипт и SSH-ключ нельзя указывать одновременно: "
                       "пропишите ssh_authorized_keys прямо в своём cloud-config."
            )

        # Шаблон окружения существует не для каждой ОС: пакеты и службы у
        # семейств называются по-разному. Отказываем сразу, а не создаём ВМ,
        # в которой шаблон молча не сработает (именно так было раньше —
        # ставились дебиановские имена пакетов на RHEL, установка падала,
        # и пользователь получал «чистую» ОС без всякого сообщения).
        tmpl = getattr(req, "cloud_init_template", None)
        if tmpl:
            from app.services.os_profiles import template_supported, TEMPLATES
            if req.os_type in ISO_INSTALL_OS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Шаблоны окружения работают только для Linux-систем с cloud-init, "
                           f"а «{req.os_type}» ставится с установочного ISO."
                )
            if not template_supported(tmpl, req.os_type):
                label = (TEMPLATES.get(tmpl) or {}).get("label", tmpl)
                raise HTTPException(
                    status_code=400,
                    detail=f"Шаблон «{label}» не поддерживается для ОС «{req.os_type}». "
                           f"Выберите другую ОС или создайте ВМ без шаблона."
                )

        db = SessionLocal()

        # Проверяем наличие свободных физических ресурсов на самом хостинге
        import os
        import shutil
        
        host_cpu = os.cpu_count() or 1
        
        host_ram_gb = 8.0
        try:
            mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
            host_ram_gb = round(mem_bytes / (1024 * 1024 * 1024), 2)
        except Exception:
            pass
            
        host_disk_gb = 80.0
        try:
            total, used, free = shutil.disk_usage("/")
            host_disk_gb = round(total / (1024 * 1024 * 1024), 2)
        except Exception:
            pass
            
        # 1. Проверяем абсолютное физическое превышение параметров
        if req.cpu_cores > host_cpu:
            db.close()
            raise HTTPException(status_code=400, detail=f"Запрошено ядер CPU ({req.cpu_cores}), которых физически нет на хосте (всего ядер: {host_cpu}).")
        if req.memory_gb > host_ram_gb:
            db.close()
            raise HTTPException(status_code=400, detail=f"Запрошено ОЗУ ({req.memory_gb} ГБ), которого физически нет на хосте (всего ОЗУ: {host_ram_gb} ГБ).")
        if req.disk_gb > host_disk_gb:
            db.close()
            raise HTTPException(status_code=400, detail=f"Запрошен размер диска ({req.disk_gb} ГБ), которого физически нет на хосте (всего памяти: {host_disk_gb} ГБ).")

        # Получаем реальное использование памяти хостом в данный момент
        current_ram_usage_gb = 0.0
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(':')] = int(parts[1])
                total_mem = meminfo.get('MemTotal', 0) * 1024
                free_mem = meminfo.get('MemFree', 0) * 1024
                buffers = meminfo.get('Buffers', 0) * 1024
                cached = meminfo.get('Cached', 0) * 1024
                used_mem = total_mem - (free_mem + buffers + cached)
                current_ram_usage_gb = round(used_mem / (1024**3), 2)
        except Exception:
            pass

        # Получаем реальное свободное место на диске хоста
        host_disk_free_gb = 0.0
        try:
            total, used, free = shutil.disk_usage("/")
            host_disk_free_gb = round(free / (1024**3), 1)
        except Exception:
            pass

        # 2. Проверяем остаток ресурсов хоста с учетом резервирования другими ВМ
        db_vms = db.query(VMTask).all()
        reserved_cpu = sum(vm.cpu_cores for vm in db_vms)
        reserved_stopped_ram = sum(vm.memory_gb for vm in db_vms if vm.status != "Running")

        available_cpu = max(0, host_cpu - reserved_cpu)
        available_ram = max(0.0, round(host_ram_gb - current_ram_usage_gb - reserved_stopped_ram, 2))
        available_disk = max(0.0, host_disk_free_gb)

        if req.cpu_cores > available_cpu:
            db.close()
            raise HTTPException(status_code=400, detail=f"Недостаточно свободных ядер CPU на хосте. Запрошено: {req.cpu_cores}, доступно для выделения: {available_cpu} (всего на хосте: {host_cpu}).")
        if req.memory_gb > available_ram:
            db.close()
            raise HTTPException(status_code=400, detail=f"Недостаточно свободной оперативной памяти на хосте. Запрошено: {req.memory_gb} ГБ, доступно для выделения: {available_ram} ГБ (всего на хосте: {host_ram_gb} ГБ).")
        if req.disk_gb > available_disk:
            db.close()
            raise HTTPException(status_code=400, detail=f"Недостаточно свободного дискового пространства на хосте. Запрошено: {req.disk_gb} ГБ, доступно для выделения: {available_disk} ГБ (всего на хосте: {host_disk_gb} ГБ).")

        # Проверяем лимиты квот для обычных пользователей (студентов)
        # Квота проверяется под блокировкой строки пользователя и в той же
        # транзакции, что и вставка ВМ, — иначе два параллельных запроса
        # прошли бы проверку одновременно и превысили лимит.
        from app.core.quotas import enforce_quota
        from app.core.ratelimit import check_rate_limit
        check_rate_limit(current_user, "create_vm")
        enforce_quota(db, current_user, add_vms=1, add_vcpus=req.cpu_cores,
                      add_ram_gb=req.memory_gb, add_storage_gb=req.disk_gb)

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
            cloud_init_template=req.cloud_init_template,
            custom_user_data=req.custom_user_data,
            iso_url=req.iso_url,
            ssh_key=req.ssh_key,
            owner_id=current_user.id,
            status="Pending"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # Генерируем дефолтные порты на основе уникального ID виртуальной машины для стабильности
        if task.os_type == "windows":
            default_ports = [
                {"ext_port": 33000 + task.id, "int_port": 3389, "name": "RDP"},
                {"ext_port": 22000 + task.id, "int_port": 22, "name": "SSH"},
                {"ext_port": 28000 + task.id, "int_port": 80, "name": "HTTP"}
            ]
        else:
            default_ports = [
                {"ext_port": 22000 + task.id, "int_port": 22, "name": "SSH"},
                {"ext_port": 28000 + task.id, "int_port": 80, "name": "HTTP"},
                {"ext_port": 44300 + task.id, "int_port": 443, "name": "HTTPS"}
            ]
        task.ports_config = json.dumps(default_ports)
        task.static_ip = compute_static_ip(task.id)
        db.commit()

        # Отправляем в RabbitMQ. Если очередь недоступна, запись уже
        # закоммичена — помечаем её как Error, чтобы она не висела в Pending
        # и не занимала квоту.
        from app.queue_client import publish_task_or_fail_task
        if not publish_task_or_fail_task("vm_tasks", {"task_id": task.id, "action": "create_vm"}, db, task):
            db.close()
            raise HTTPException(status_code=503, detail="Сервис очередей недоступен, попробуйте позже.")

        db.close()
        return {"status": "creating", "name": req.name, "task_id": task.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class VMCloneRequest(BaseModel):
    new_name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя новой (клонированной) ВМ")


@router.post("/{name}/clone", status_code=status.HTTP_201_CREATED)
def clone_vm(name: str, req: VMCloneRequest, current_user: User = Depends(get_current_user)):
    """Клонировать существующую ВМ в новую локальную ВМ (копия диска + новый инстанс)."""
    check_vm_ownership(name, current_user)

    from app.db import SessionLocal
    from app.models.models import VMTask
    from app.queue_client import publish_task
    import json as _json

    db = SessionLocal()
    try:
        source = db.query(VMTask).filter(VMTask.name == name).first()
        if not source:
            raise HTTPException(status_code=404, detail="Исходная ВМ не найдена.")

        new_name = req.new_name
        if new_name == name:
            raise HTTPException(status_code=400, detail="Имя клона должно отличаться от исходной ВМ.")
        if db.query(VMTask).filter(VMTask.name == new_name).first():
            raise HTTPException(status_code=400, detail="ВМ с таким именем уже существует или создаётся.")

        # Квоты студента: клон занимает столько же ресурсов, сколько исходная ВМ
        if current_user.role != "admin":
            owned = db.query(VMTask).filter(VMTask.owner_id == current_user.id).all()
            if len(owned) + 1 > current_user.max_vms:
                raise HTTPException(status_code=400, detail=f"Превышена квота на количество ВМ ({current_user.max_vms}).")
            if sum(v.cpu_cores for v in owned) + source.cpu_cores > current_user.max_vcpus:
                raise HTTPException(status_code=400, detail=f"Превышена квота на ядра CPU (лимит: {current_user.max_vcpus}).")
            if sum(v.memory_gb * 1024 for v in owned) + source.memory_gb * 1024 > current_user.max_ram_mb:
                raise HTTPException(status_code=400, detail=f"Превышена квота на ОЗУ (лимит: {current_user.max_ram_mb} МБ).")
            if sum(v.disk_gb for v in owned) + source.disk_gb > current_user.max_storage_gb:
                raise HTTPException(status_code=400, detail=f"Превышена квота на диск (лимит: {current_user.max_storage_gb} ГБ).")

        # Проверяем свободное место на хосте (диск клонируется целиком)
        import shutil
        try:
            _, _, free = shutil.disk_usage("/")
            free_gb = round(free / (1024**3), 1)
            if source.disk_gb > free_gb:
                raise HTTPException(status_code=400, detail=f"Недостаточно места на хосте для копии диска: нужно {source.disk_gb} ГБ, свободно {free_gb} ГБ.")
        except HTTPException:
            raise
        except Exception:
            pass

        clone = VMTask(
            name=new_name,
            os_type=source.os_type,
            cpu_cores=source.cpu_cores,
            memory_gb=source.memory_gb,
            disk_gb=source.disk_gb,
            custom_image=source.custom_image,
            packages=source.packages,
            network_drives=source.network_drives,
            cloud_init_template=source.cloud_init_template,
            custom_user_data=source.custom_user_data,
            # Клон загрузится с cloud-init исходной ВМ, значит и пароль внутри
            # будет тот же — переносим его, чтобы Secret клона не разошёлся.
            vm_password=source.vm_password,
            iso_url=source.iso_url,
            ssh_key=source.ssh_key,
            owner_id=current_user.id,
            status="Pending",
        )
        db.add(clone)
        db.commit()
        db.refresh(clone)

        # Стабильные порты по ID клона (как при обычном создании)
        if clone.os_type == "windows":
            default_ports = [
                {"ext_port": 33000 + clone.id, "int_port": 3389, "name": "RDP"},
                {"ext_port": 22000 + clone.id, "int_port": 22, "name": "SSH"},
                {"ext_port": 28000 + clone.id, "int_port": 80, "name": "HTTP"},
            ]
        else:
            default_ports = [
                {"ext_port": 22000 + clone.id, "int_port": 22, "name": "SSH"},
                {"ext_port": 28000 + clone.id, "int_port": 80, "name": "HTTP"},
                {"ext_port": 44300 + clone.id, "int_port": 443, "name": "HTTPS"},
            ]
        clone.ports_config = _json.dumps(default_ports)
        clone.static_ip = compute_static_ip(clone.id)
        db.commit()

        publish_task("vm_tasks", {
            "task_id": clone.id,
            "action": "clone_vm",
            "source_name": name,
        })
        return {"status": "cloning", "name": new_name, "task_id": clone.id, "source": name}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{name}")
def delete_vm(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    try:
        res = client.delete_vm(name)
        
        db = SessionLocal()
        try:
            db_vm = db.query(VMTask).filter(VMTask.name == name).first()
            if db_vm:
                from app.models.models import AppDeployment, UserDatabase, UserVolume
                # Отвязываем БД от ВМ (сама БД — отдельный ресурс, не удаляем)
                db.query(UserDatabase).filter(UserDatabase.associated_vm_id == db_vm.id).update({"associated_vm_id": None})
                # Если ВМ была частью деплоя приложения — удаляем и запись деплоя
                db.query(AppDeployment).filter(AppDeployment.vm_id == db_vm.id).delete()
                # Каскад: удаляем привязанные к ВМ сетевые диски (PVC + запись)
                for vol in db.query(UserVolume).filter(UserVolume.attached_vm_id == db_vm.id).all():
                    try:
                        client.delete_pvc(vol.name)
                    except Exception as e:
                        logger.warning(f"Не удалось удалить PVC {vol.name} при удалении ВМ {name}: {e}")
                    db.delete(vol)
                db.flush()

                db.delete(db_vm)
                db.commit()
        finally:
            db.close()
            
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/start")
def start_vm(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    db = SessionLocal()
    try:
        db_vm = db.query(VMTask).filter(VMTask.name == name).first()
        if db_vm:
            db_vm.status = "Starting"
            db.commit()
    except Exception as db_err:
        logger.error(f"Failed to set VM {name} status to Starting in DB: {db_err}")
    finally:
        db.close()
    try:
        return client.start_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/stop")
def stop_vm(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    db = SessionLocal()
    try:
        db_vm = db.query(VMTask).filter(VMTask.name == name).first()
        if db_vm:
            db_vm.status = "Stopping"
            db.commit()
    except Exception as db_err:
        logger.error(f"Failed to set VM {name} status to Stopping in DB: {db_err}")
    finally:
        db.close()
    try:
        return client.stop_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/restart")
def restart_vm(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    db = SessionLocal()
    try:
        db_vm = db.query(VMTask).filter(VMTask.name == name).first()
        if db_vm:
            db_vm.status = "Starting"
            db.commit()
    except Exception as db_err:
        logger.error(f"Failed to set VM {name} status to Starting in DB: {db_err}")
    finally:
        db.close()
    try:
        return client.restart_vm(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/metrics")
def get_vm_metrics(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    try:
        return client.get_vm_metrics(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- НОВЫЕ МАРШРУТЫ ИЗМЕНЕНИЯ РЕСУРСОВ И БЭКАПОВ ---

@router.post("/{name}/resize")
def resize_vm(name: str, req: VMResizeRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Изменение лимитов CPU, RAM и расширение HDD"""
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    
    db = SessionLocal()
    try:
        if current_user.role != "admin":
            # Проверяем квоты
            other_vms = db.query(VMTask).filter(VMTask.owner_id == current_user.id, VMTask.name != name).all()
            total_cpus = sum(vm.cpu_cores for vm in other_vms)
            total_ram = sum(vm.memory_gb * 1024 for vm in other_vms)
            total_storage = sum(vm.disk_gb for vm in other_vms)
            
            if total_cpus + req.cpu_cores > current_user.max_vcpus:
                raise HTTPException(status_code=400, detail=f"Превышена квота на ядра процессора (Лимит: {current_user.max_vcpus}).")
            if total_ram + (req.memory_gb * 1024) > current_user.max_ram_mb:
                raise HTTPException(status_code=400, detail=f"Превышена квота на оперативную память (Лимит: {current_user.max_ram_mb} МБ).")
            if total_storage + req.disk_gb > current_user.max_storage_gb:
                raise HTTPException(status_code=400, detail=f"Превышена квота на дисковое пространство (Лимит: {current_user.max_storage_gb} ГБ).")

        # Изменяем CPU/RAM
        client.resize_vm_resources(name, req.cpu_cores, req.memory_gb)
        # Расширяем диск
        client.resize_vm_disk(name, req.disk_gb)
        
        # Обновляем в БД
        db_vm = db.query(VMTask).filter(VMTask.name == name).first()
        if db_vm:
            db_vm.cpu_cores = req.cpu_cores
            db_vm.memory_gb = req.memory_gb
            db_vm.disk_gb = req.disk_gb
            db.commit()
            
        return {"status": "resized", "name": name, "cpu_cores": req.cpu_cores, "memory_gb": req.memory_gb, "disk_gb": req.disk_gb}
    finally:
        db.close()

@router.post("/{name}/settings")
def update_vm_settings(name: str, req: VMSettingsUpdateRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Обновление настроек ВМ (ресурсы, лимиты диска, проброс портов, фаервол)"""
    check_vm_ownership(name, current_user)
    from app.db import SessionLocal
    from app.models.models import VMTask
    import json
    
    try:
        db = SessionLocal()
        try:
            db_vm = db.query(VMTask).filter(VMTask.name == name).first()
            if not db_vm:
                raise HTTPException(status_code=404, detail="ВМ не найдена в БД")
                
            # Проверяем квоты при изменении параметров CPU/RAM/HDD
            if current_user.role != "admin":
                other_vms = db.query(VMTask).filter(VMTask.owner_id == current_user.id, VMTask.name != name).all()
                total_cpus = sum(vm.cpu_cores for vm in other_vms)
                total_ram = sum(vm.memory_gb * 1024 for vm in other_vms)
                total_storage = sum(vm.disk_gb for vm in other_vms)
                
                if total_cpus + req.cpu_cores > current_user.max_vcpus:
                    raise HTTPException(status_code=400, detail=f"Превышена квота на ядра процессора (Лимит: {current_user.max_vcpus}).")
                if total_ram + (req.memory_gb * 1024) > current_user.max_ram_mb:
                    raise HTTPException(status_code=400, detail=f"Превышена квота на оперативную память (Лимит: {current_user.max_ram_mb} МБ).")
                if total_storage + req.disk_gb > current_user.max_storage_gb:
                    raise HTTPException(status_code=400, detail=f"Превышена квота на дисковое пространство (Лимит: {current_user.max_storage_gb} ГБ).")
                
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
                reconcile_vm_firewall_rules(ip, db_vm.id, db_vm.ports_config, db_vm.firewall_rules, db_vm.os_type)
                
            return {"status": "success", "message": "Настройки ВМ сохранены"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating VM settings for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/metrics/history")
def get_vm_metrics_history(name: str, range_hours: int = Query(1, ge=1, le=24), client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Получение истории метрик CPU/RAM из Prometheus за указанный период (в часах)"""
    check_vm_ownership(name, current_user, need="viewer")
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
def create_backup(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Создать резервную копию VM"""
    check_vm_ownership(name, current_user)
    try:
        return client.create_vm_backup(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}/backups")
def list_backups(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Получить список резервных копий VM"""
    check_vm_ownership(name, current_user, need="viewer")
    try:
        return client.list_vm_backups(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{name}/backups/{backup_name}")
def delete_backup(name: str, backup_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    """Удалить резервную копию"""
    check_vm_ownership(name, current_user)
    try:
        return client.delete_vm_backup(backup_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/restore/{backup_name}")
def restore_vm_backup(name: str, backup_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
    try:
        return client.restore_vm_backup(name, backup_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def resolve_vm_ip(ips: list) -> Optional[str]:
    """Совместимый алиас app.core.netutils.pick_external_ip.

    Раньше здесь была отдельная копия той же логики фильтрации, которая не
    знала про 192.168.100.x (изолированную сеть кластеров) — SSH/терминал
    ВМ в кластере мог получить как «внешний» адрес изоляции кластера вместо
    настоящего мостового IP. netutils.pick_external_ip — единая точка правды,
    её и используют все остальные места (деплои, домены, реестр, файрвол)."""
    from app.core.netutils import pick_external_ip
    return pick_external_ip(ips)


class VMCommandExecuteRequest(BaseModel):
    command: str = Field(..., description="Команда для выполнения на ВМ через SSH")
    cwd: Optional[str] = Field(None, description="Текущая рабочая директория")


@router.get("/{name}/ssh-details")
def get_vm_ssh_details(name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
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
def execute_vm_ssh_command(name: str, req: VMCommandExecuteRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(name, current_user)
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
async def migrate_vm(name: str, target_server_id: str = Query(...), k8s: K8sClient = Depends(get_k8s_client), db: AsyncSession = Depends(get_db), current_user: User = Depends(check_admin)):
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
            from app.core.crypto import decrypt_secret
            ssh.connect(
                target_server.host,
                port=target_server.port,
                username=target_server.username,
                password=decrypt_secret(target_server.password),
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
            scp_args = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-i", key_path,
                disk_path,
                f"{target_server.username}@{target_server.host}:/opt/antigravity/vms/{name}/disk.img"
            ]
            scp_res = subprocess.run(nsenter_prefix + scp_args, capture_output=True, text=True)
            
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

# --- УПРАВЛЕНИЕ БАЛАНСИРОВОЧНЫМИ ПУЛАМИ (Nginx) ---

POOLS_FILE = "/app/data/balancer_pools.json"

# Порты, которые уже слушает сама платформа. Балансировщик поднимается nginx'ом
# в сети хоста, поэтому пул на занятом порту не даст nginx перезагрузиться —
# и вместе с ним отвалятся ОСТАЛЬНЫЕ пулы. Особенно опасны 8080/8443 (сама
# панель) и 80/443 (прокси доменов: без 80 не пройдёт проверка Let's Encrypt).
RESERVED_HOST_PORTS = {
    25, 143, 587, 993,   # почтовый сервер
    80, 443,             # aegis-caddy: домены и выпуск TLS-сертификатов
    3306,                # MariaDB
    5000,                # aegis-registry: приватный реестр образов
    5432,                # PostgreSQL
    5672, 15672,         # RabbitMQ и его веб-консоль
    8000,                # API бэкенда
    8001,                # Go-оркестратор
    8080, 8443,          # веб-панель (frontend)
    8081, 8444,          # кабинет пользователя
    8082,                # webmail
    9000, 9001,          # MinIO: S3 API и консоль
}


class BalancerPoolCreate(BaseModel):
    name: str
    port: int
    method: str
    vms: List[str]
    backend_port: int = 80

def load_balancer_pools() -> list:
    import json
    import os
    if os.path.exists(POOLS_FILE):
        try:
            with open(POOLS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading pools: {e}")
    return []

def save_balancer_pools(pools: list):
    import json
    import os
    os.makedirs(os.path.dirname(POOLS_FILE), exist_ok=True)
    try:
        with open(POOLS_FILE, "w") as f:
            json.dump(pools, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving pools: {e}")

@router.get("/balancer/pools", response_model=List[dict])
def get_balancer_pools(current_user: User = Depends(get_current_user)):
    """Получить список активных балансировочных пулов"""
    return load_balancer_pools()

@router.post("/balancer/pools")
def create_balancer_pool(payload: BalancerPoolCreate, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(check_admin)):
    """Создать новый балансировочный пул и применить конфигурацию Nginx на хосте"""
    import os
    import subprocess
    from app.core.netutils import is_safe_name, is_valid_ipv4

    # ЗАЩИТА ОТ ИНЪЕКЦИИ: имя пула попадает и в конфиг Nginx, и в имя файла на хосте.
    if not is_safe_name(payload.name):
        raise HTTPException(status_code=400, detail="Имя пула может содержать только строчные латинские буквы, цифры и дефис.")
    if not (1 <= payload.port <= 65535) or not (1 <= payload.backend_port <= 65535):
        raise HTTPException(status_code=400, detail="Некорректный порт.")

    pools = load_balancer_pools()
    
    # 1. Проверяем уникальность имени
    if any(p["name"] == payload.name for p in pools):
        raise HTTPException(status_code=400, detail=f"Пул с именем {payload.name} уже существует")
        
    # 2. Проверяем порты
    if payload.port in RESERVED_HOST_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Порт {payload.port} занят самой платформой. "
                   "Пул на нём не даст nginx перезагрузиться и сломает остальные пулы. "
                   "Выберите свободный порт (например, из диапазона 10000–20000)."
        )
    if payload.backend_port in RESERVED_HOST_PORTS and payload.backend_port not in (80, 443):
        # backend_port — порт ВНУТРИ ВМ, там 80/443 совершенно нормальны
        logger.warning(f"Балансировщик {payload.name}: необычный порт бэкенда {payload.backend_port}")
         
    # 3. Собираем IP-адреса виртуальных машин
    servers = []
    for vm_name in payload.vms:
        try:
            vm_info = client.get_vm(vm_name)
            ips = vm_info.get("ips", [])
            
            # Выбираем лучший IP: предпочитаем физический/мостовой IP перед flannel-IP 10.244.x.x
            best_ip = None
            for ip in ips:
                if ip and not ip.startswith("127."):
                    if not ip.startswith("10.244."):
                        best_ip = ip
                        break
            
            # Если нет внешнего/мостового IP, берем любой доступный
            if not best_ip and ips:
                best_ip = ips[0]
                
            if best_ip and is_valid_ipv4(best_ip):
                servers.append(f"server {best_ip}:{payload.backend_port};")
            elif best_ip:
                logger.warning(f"Пропускаю ВМ {vm_name}: некорректный IP {best_ip!r}")
        except Exception as e:
            logger.error(f"Error resolving IP for VM {vm_name}: {e}")
            
    if not servers:
        raise HTTPException(status_code=400, detail="Ни одна из выбранных виртуальных машин не запущена или не имеет IP-адреса")
        
    # 4. Генерируем конфигурацию Nginx
    method_directive = ""
    if payload.method == "Least Connections":
        method_directive = "least_conn;"
    elif payload.method == "IP Hash":
        method_directive = "ip_hash;"
        
    servers_str = "\n    ".join(servers)
    
    nginx_config = f"""upstream balancer_{payload.name} {{
    {method_directive}
    {servers_str}
}}

server {{
    listen {payload.port};
    server_name _;
    
    location / {{
        proxy_pass http://balancer_{payload.name};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
    
    # 5. Записываем конфигурацию в хост Nginx директорию
    host_nginx_dir = "/proc/1/root/etc/nginx/conf.d"
    os.makedirs(host_nginx_dir, exist_ok=True)
    config_path = os.path.join(host_nginx_dir, f"aegis_balancer_{payload.name}.conf")
    
    try:
        with open(config_path, "w") as f:
            f.write(nginx_config)
    except Exception as write_err:
        raise HTTPException(status_code=500, detail=f"Не удалось записать конфигурацию Nginx: {write_err}")
        
    # 6. Перезапускаем Nginx на хосте
    nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
    
    # Ищем путь к исполняемому файлу Nginx на хосте
    which_res = subprocess.run(nsenter_prefix + ["which nginx || find /usr/sbin /usr/local/nginx/sbin /usr/bin -name nginx 2>/dev/null"], capture_output=True, text=True, timeout=5)
    nginx_bin = None
    if which_res.returncode == 0:
        lines = [line.strip() for line in which_res.stdout.splitlines() if line.strip()]
        if lines:
            nginx_bin = lines[0]
            
    if not nginx_bin:
        # Откат изменений
        if os.path.exists(config_path):
            os.remove(config_path)
        raise HTTPException(
            status_code=400, 
            detail="Nginx не установлен на основном хост-сервере. Пожалуйста, выполните 'sudo apt update && sudo apt install -y nginx' на хосте 192.168.31.14."
        )
        
    # Проверка конфигурации
    test_res = subprocess.run(nsenter_prefix + [f"{nginx_bin} -t"], capture_output=True, text=True, timeout=5)
    if test_res.returncode != 0:
        if os.path.exists(config_path):
            os.remove(config_path)
        raise HTTPException(status_code=400, detail=f"Конфигурация Nginx не прошла валидацию: {test_res.stderr or test_res.stdout}")
        
    # Перезапуск
    reload_res = subprocess.run(nsenter_prefix + [f"{nginx_bin} -s reload"], capture_output=True, text=True, timeout=5)
    if reload_res.returncode != 0:
        if os.path.exists(config_path):
            os.remove(config_path)
        raise HTTPException(status_code=500, detail=f"Ошибка перезапуска Nginx: {reload_res.stderr or reload_res.stdout}")
        
    # 7. Добавляем в список пулов и сохраняем
    new_pool = {
        "name": payload.name,
        "port": payload.port,
        "method": payload.method,
        "vms": payload.vms,
        "backend_port": payload.backend_port,
        "requestsPerSec": 0
    }
    pools.append(new_pool)
    save_balancer_pools(pools)
    
    return {"status": "success", "message": f"Пул балансировки {payload.name} успешно запущен на порту {payload.port}"}

@router.delete("/balancer/pools/{name}")
def delete_balancer_pool(name: str, current_user: User = Depends(check_admin)):
    """Удалить балансировочный пул и стереть его конфигурацию из Nginx на хосте"""
    import os
    import subprocess
    from app.core.netutils import is_safe_name

    # ЗАЩИТА ОТ PATH TRAVERSAL: имя уходит в путь файла на хосте.
    if not is_safe_name(name):
        raise HTTPException(status_code=400, detail="Некорректное имя пула.")

    pools = load_balancer_pools()
    pool_to_delete = next((p for p in pools if p["name"] == name), None)
    if not pool_to_delete:
        raise HTTPException(status_code=404, detail=f"Пул с именем {name} не найден")
        
    # 1. Удаляем файл конфигурации Nginx
    config_path = f"/proc/1/root/etc/nginx/conf.d/aegis_balancer_{name}.conf"
    if os.path.exists(config_path):
        try:
            os.remove(config_path)
        except Exception as e:
            logger.error(f"Failed to remove Nginx config {config_path}: {e}")
            
    # 2. Перезапускаем Nginx на хосте
    nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
    which_res = subprocess.run(nsenter_prefix + ["which nginx || find /usr/sbin /usr/local/nginx/sbin /usr/bin -name nginx 2>/dev/null"], capture_output=True, text=True, timeout=5)
    nginx_bin = "nginx"
    if which_res.returncode == 0:
        lines = [line.strip() for line in which_res.stdout.splitlines() if line.strip()]
        if lines:
            nginx_bin = lines[0]
    subprocess.run(nsenter_prefix + [f"{nginx_bin} -s reload"], capture_output=True, timeout=5)
    
    # 3. Обновляем список пулов
    updated_pools = [p for p in pools if p["name"] != name]
    save_balancer_pools(updated_pools)
    
    return {"status": "success", "message": f"Пул балансировки {name} успешно удален"}
