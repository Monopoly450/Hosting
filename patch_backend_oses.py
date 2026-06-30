import re

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# 1. Update OS Image Constants
constants_old = """# Базовые константы-шаблоны для генерации манифестов
DEFAULT_WINDOWS_ISO = "https://go.microsoft.com/fwlink/p/?LinkID=2195280"
DEFAULT_UBUNTU_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
"""

constants_new = """# Базовые константы-шаблоны для генерации манифестов
DEFAULT_WINDOWS_ISO = "https://go.microsoft.com/fwlink/p/?LinkID=2195280"
DEFAULT_UBUNTU_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
DEFAULT_CENTOS_IMAGE = "https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2"
DEFAULT_DEBIAN_IMAGE = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
DEFAULT_PROXMOX_ISO = "http://download.proxmox.com/iso/proxmox-ve_8.2-1.iso"
"""

if "DEFAULT_CENTOS_IMAGE" not in app:
    app = app.replace(constants_old, constants_new)

# 2. Rename and update generate_ubuntu_manifest -> generate_linux_manifest
# Wait, let's just do a string replacement for the generate_ubuntu_manifest definition

# Find generate_ubuntu_manifest definition start
idx_start = app.find('def generate_ubuntu_manifest(req: VMCreationRequest, password: str) -> dict:')
idx_end = app.find('def generate_windows_manifest(req: VMCreationRequest) -> dict:')

if idx_start != -1 and idx_end != -1:
    linux_manifest_str = app[idx_start:idx_end]
    
    # Let's replace the whole block dynamically by rewriting parts of it
    
    # 2.1 Rename it
    new_linux = linux_manifest_str.replace('def generate_ubuntu_manifest', 'def generate_linux_manifest')
    
    # 2.2 Image URL & Default User Logic
    image_logic_old = """    # Если выбран кастомный образ, загружаем его из локального хранилища бэкенда
    image_url = DEFAULT_UBUNTU_IMAGE
    if req.os_type == "custom" and req.custom_image:
        host_ip = get_host_ip()
        image_url = f"http://{host_ip}:8000/api/images/{req.custom_image}"
"""

    image_logic_new = """    # Определение базового образа и логина
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
        image_url = f"http://{host_ip}:8000/api/images/{req.custom_image}"
"""
    new_linux = new_linux.replace(image_logic_old, image_logic_new)
    
    # 2.3 Bitrix Script Logic inside packages_yaml
    bitrix_logic = """
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            packages_yaml += "\\n  - wget"
        runcmd_yaml = "\\nruncmd:\\n  - [ wget, \\"http://repos.1c-bitrix.ru/yum/bitrix-env.sh\\" ]\\n  - [ chmod, \\"+x\\", \\"bitrix-env.sh\\" ]\\n  - [ ./bitrix-env.sh, \\"-s\\", \\"-p\\", \\"-H\\", req.name ]\\n"
    else:
        runcmd_yaml = ""
"""
    
    # Find where packages_yaml ends
    mounts_idx = new_linux.find('    # Обработка сетевых дисков')
    if mounts_idx != -1:
        new_linux = new_linux[:mounts_idx] + bitrix_logic + new_linux[mounts_idx:]

    # Inject runcmd_yaml and default_user into userData
    userdata_old = """ssh_pwauth: True{packages_yaml}{mounts_yaml}
chpasswd:
  list: |
    ubuntu:{password}"""

    userdata_new = """ssh_pwauth: True{packages_yaml}{mounts_yaml}{runcmd_yaml}
chpasswd:
  list: |
    {default_user}:{password}"""
    
    new_linux = new_linux.replace(userdata_old, userdata_new)
    
    # Replace default user in users list
    users_old = """users:
  - name: ubuntu"""
    users_new = """users:
  - name: {default_user}"""
    
    new_linux = new_linux.replace(users_old, users_new)
    
    app = app[:idx_start] + new_linux + app[idx_end:]


# 3. Rename generate_windows_manifest -> generate_iso_manifest
idx_start2 = app.find('def generate_windows_manifest(req: VMCreationRequest) -> dict:')
idx_end2 = app.find('@router.post("/")')

if idx_start2 != -1 and idx_end2 != -1:
    iso_manifest_str = app[idx_start2:idx_end2]
    
    new_iso = iso_manifest_str.replace('def generate_windows_manifest', 'def generate_iso_manifest')
    
    image_logic_old = """    # Поддержка кастомного ISO
    iso_url = req.iso_url if req.iso_url else DEFAULT_WINDOWS_ISO"""
    
    image_logic_new = """    iso_url = DEFAULT_WINDOWS_ISO
    if req.os_type == "proxmox":
        iso_url = DEFAULT_PROXMOX_ISO
        
    if req.iso_url:
        iso_url = req.iso_url
    elif req.os_type == "custom" and req.custom_image:
        host_ip = get_host_ip()
        iso_url = f"http://{host_ip}:8000/api/images/{req.custom_image}"
"""
    new_iso = new_iso.replace(image_logic_old, image_logic_new)
    
    app = app[:idx_start2] + new_iso + app[idx_end2:]


# 4. Update create_vm route
create_vm_old = """        if req.os_type in ["ubuntu", "custom"]:
            manifest = generate_ubuntu_manifest(req, generated_password)
        elif req.os_type == "windows":
            manifest = generate_windows_manifest(req)"""

create_vm_new = """        if req.os_type in ["ubuntu", "centos", "debian", "bitrix", "custom"]:
            manifest = generate_linux_manifest(req, generated_password)
            username = "cloud-user" if req.os_type in ["centos", "bitrix"] else ("debian" if req.os_type == "debian" else "ubuntu")
        elif req.os_type in ["windows", "proxmox"]:
            manifest = generate_iso_manifest(req)
            username = "Administrator" # Windows or Installer default"""

if "generate_ubuntu_manifest" in app:
    app = app.replace(create_vm_old, create_vm_new)
else:
    # If the logic in create_vm didn't have generate_ubuntu_manifest (wait, it did, we replaced it above)
    app = app.replace(create_vm_old, create_vm_new)

with open(app_file, "w") as f:
    f.write(app)

print("Backend API fully patched for OS types.")
