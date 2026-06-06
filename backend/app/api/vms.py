from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.core.k8s_client import K8sClient

router = APIRouter()

# Зависимость для получения клиента K8s
def get_k8s_client():
    return K8sClient()

# Модели запросов
class VMCreationRequest(BaseModel):
    name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя виртуалки (латиница, цифры, дефис)")
    os_type: str = Field(..., description="Тип ОС (ubuntu или windows)")
    cpu_cores: int = Field(2, ge=1, le=16, description="Количество ядер CPU")
    memory_gb: int = Field(2, ge=1, le=64, description="Объем оперативной памяти в ГБ")
    disk_gb: int = Field(20, ge=10, le=500, description="Размер системного диска в ГБ")
    password: Optional[str] = Field("ubuntu", description="Пароль для пользователя по умолчанию")
    iso_url: Optional[str] = Field(None, description="Ссылка на собственный ISO-образ (для Windows)")

# Базовые константы-шаблоны для генерации манифестов
DEFAULT_WINDOWS_ISO = "https://software-static.download.prss.microsoft.com/sg/download/details.aspx?uuid=5e4c6052-b13c-4384-9ff5-c439162e08e7"
DEFAULT_UBUNTU_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"

def generate_ubuntu_manifest(req: VMCreationRequest) -> dict:
    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": req.name,
            "namespace": "default",
            "labels": {
                "hosting.antigravity.io/template": "ubuntu"
            }
        },
        "spec": {
            "running": True, # Сразу запускаем после создания
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
                                    "disk": {
                                        "bus": "virtio"
                                    }
                                }
                            ],
                            "interfaces": [
                                {
                                    "name": "default",
                                    "masquerade": {}
                                },
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
                            "name": "default",
                            "pod": {}
                        },
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
                                "userData": f"#cloud-config\nssh_pwauth: True\ndisable_root: false\nusers:\n  - name: ubuntu\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    lock_passwd: false\n    passwd: {req.password}\nruncmd:\n  - apt-get update\n  - apt-get install -y qemu-guest-agent\n  - systemctl enable --now qemu-guest-agent\n"
                            }
                        }
                    ]
                }
            },
            "dataVolumeTemplates": [
                {
                    "metadata": {
                        "name": f"{req.name}-disk"
                    },
                    "spec": {
                        "source": {
                            "http": {
                                "url": DEFAULT_UBUNTU_IMAGE
                            }
                        },
                        "storage": {
                            "storageClassName": "local-path",
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
    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": req.name,
            "namespace": "default",
            "labels": {
                "hosting.antigravity.io/template": "windows"
            }
        },
        "spec": {
            "running": True, # Сразу запускаем
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
                                    "name": "default",
                                    "masquerade": {}
                                },
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
                            "name": "default",
                            "pod": {}
                        },
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
                        "name": f"{req.name}-hd"
                    },
                    "spec": {
                        "source": {
                            "blank": {}
                        },
                        "storage": {
                            "storageClassName": "local-path",
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
                        "name": f"{req.name}-iso"
                    },
                    "spec": {
                        "source": {
                            "http": {
                                "url": iso_url
                            }
                        },
                        "storage": {
                            "storageClassName": "local-path",
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
        raise HTTPException(status_code=404, detail=f"Виртуальная машина {name} не найдена или ошибка API: {e}")

@router.post("", status_code=status.HTTP_201_CREATED)
def create_vm(req: VMCreationRequest, client: K8sClient = Depends(get_k8s_client)):
    try:
        if req.os_type == "ubuntu":
            manifest = generate_ubuntu_manifest(req)
        elif req.os_type == "windows":
            manifest = generate_windows_manifest(req)
        else:
            raise HTTPException(status_code=400, detail="Поддерживаются только шаблоны ubuntu и windows.")
            
        client.create_vm_from_manifest(manifest)
        return {"status": "creating", "name": req.name}
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
