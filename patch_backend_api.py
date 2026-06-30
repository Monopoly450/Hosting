import re

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# 1. Update VMCreationRequest
req_str = """class VMCreationRequest(BaseModel):
    name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя виртуалки (латиница, цифры, дефис)")
    os_type: str = Field(..., description="Тип ОС (ubuntu, windows или custom)")
    custom_image: Optional[str] = Field(None, description="Имя файла кастомного образа (если os_type == custom)")
    cpu_cores: int = Field(2, ge=1, le=16, description="Количество ядер CPU")
    memory_gb: int = Field(2, ge=1, le=64, description="Объем оперативной памяти в ГБ")
    disk_gb: int = Field(20, ge=10, le=500, description="Размер системного диска в ГБ")
    iso_url: Optional[str] = Field(None, description="Ссылка на собственный ISO-образ (для Windows)")"""

new_req_str = """class VMCreationRequest(BaseModel):
    name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя виртуалки (латиница, цифры, дефис)")
    os_type: str = Field(..., description="Тип ОС (ubuntu, windows или custom)")
    custom_image: Optional[str] = Field(None, description="Имя файла кастомного образа (если os_type == custom)")
    cpu_cores: int = Field(2, ge=1, le=16, description="Количество ядер CPU")
    memory_gb: int = Field(2, ge=1, le=64, description="Объем оперативной памяти в ГБ")
    disk_gb: int = Field(20, ge=10, le=500, description="Размер системного диска в ГБ")
    iso_url: Optional[str] = Field(None, description="Ссылка на собственный ISO-образ (для Windows)")
    packages: Optional[str] = Field(None, description="Пакеты для установки (через запятую)")
    network_drives: Optional[str] = Field(None, description="Сетевые диски (NFS/PVC через запятую)")"""

app = app.replace(req_str, new_req_str)

# 2. Update generate_ubuntu_manifest
# Find generate_ubuntu_manifest function
start_idx = app.find('def generate_ubuntu_manifest(req: VMCreationRequest, password: str) -> dict:')

# We need to build cloud_init dynamic blocks
cloud_init_logic = """
    # Обработка пакетов
    packages_yaml = ""
    if req.packages:
        pkgs = [p.strip() for p in req.packages.split(",") if p.strip()]
        if pkgs:
            packages_yaml = "\\npackages:\\n" + "\\n".join([f"  - {p}" for p in pkgs])
            
    # Обработка сетевых дисков
    mounts_yaml = ""
    extra_volumes = []
    extra_disks = []
    
    if req.network_drives:
        drives = [d.strip() for d in req.network_drives.split(",") if d.strip()]
        mounts_list = []
        for idx, drive in enumerate(drives):
            if ":/" in drive:
                # Это NFS или SMB (упрощенно считаем NFS)
                mounts_list.append(f"  - [ {drive}, /mnt/network_drive_{idx}, nfs, \\"defaults\\", \\"0\\", \\"0\\" ]")
            else:
                # Считаем что это существующий PVC
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
            mounts_yaml = "\\nmounts:\\n" + "\\n".join(mounts_list)
            # Также добавим пакет nfs-common если его нет
            if "nfs-common" not in packages_yaml:
                if packages_yaml:
                    packages_yaml += "\\n  - nfs-common"
                else:
                    packages_yaml = "\\npackages:\\n  - nfs-common"
"""

# Replace the beginning of generate_ubuntu_manifest
if 'packages_yaml' not in app:
    app = app.replace(
        '    return {\n        "apiVersion": "kubevirt.io/v1",',
        cloud_init_logic + '\n    return {\n        "apiVersion": "kubevirt.io/v1",'
    )

# Now we need to inject packages_yaml and mounts_yaml into userData
userdata_str = """                                "userData": f\"\"\"#cloud-config
ssh_pwauth: True"""

new_userdata_str = """                                "userData": f\"\"\"#cloud-config
ssh_pwauth: True{packages_yaml}{mounts_yaml}"""

app = app.replace(userdata_str, new_userdata_str)

# Now inject extra_disks into the disks list
disks_str = """                            "disks": [
                                {
                                    "disk": {
                                        "bus": "virtio"
                                    },
                                    "name": f"{req.name}-disk"
                                },
                                {
                                    "name": "cloudinit",
                                    "disk": {
                                        "bus": "virtio"
                                    }
                                }
                            ]"""

# Since it's a python dict literal we have to inject the list elements
# Actually, since we build the dict, we can't easily dynamically append to the array in the literal if it's purely a literal.
# Wait, it's returning a huge dict. Let's modify the function to build the dict first, then append.
