import re

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# We need to inject the package and disk parsing logic right before manifest = {
parsing_logic = """
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
                mounts_list.append(f"  - [ {drive}, /mnt/network_drive_{idx}, nfs, \\"defaults\\", \\"0\\", \\"0\\" ]")
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
            mounts_yaml = "\\nmounts:\\n" + "\\n".join(mounts_list)
            if "nfs-common" not in packages_yaml:
                if packages_yaml:
                    packages_yaml += "\\n  - nfs-common"
                else:
                    packages_yaml = "\\npackages:\\n  - nfs-common"

    # Специфично для Bitrix
    runcmd_yaml = ""
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            if packages_yaml:
                packages_yaml += "\\n  - wget"
            else:
                packages_yaml = "\\npackages:\\n  - wget"
        runcmd_yaml = "\\nruncmd:\\n  - [ wget, \\"http://repos.1c-bitrix.ru/yum/bitrix-env.sh\\" ]\\n  - [ chmod, \\"+x\\", \\"bitrix-env.sh\\" ]\\n  - [ ./bitrix-env.sh, \\"-s\\", \\"-p\\", \\"-H\\", req.name ]\\n"
"""

# Let's insert this right before `    manifest = {`
target = "    manifest = {"
if parsing_logic.strip().split("\\n")[0] not in app:
    app = app.replace(target, parsing_logic + "\n" + target)

# Now we need to update the userData in manifest to actually use {packages_yaml}{mounts_yaml}{runcmd_yaml}
# Currently it's:
# ssh_pwauth: True
# disable_root: false
# chpasswd:
# Let's replace `ssh_pwauth: True\ndisable_root: false` with `ssh_pwauth: True{packages_yaml}{mounts_yaml}{runcmd_yaml}\ndisable_root: false`
old_userdata = """ssh_pwauth: True
disable_root: false"""
new_userdata = """ssh_pwauth: True{packages_yaml}{mounts_yaml}{runcmd_yaml}
disable_root: false"""

app = app.replace(old_userdata, new_userdata)

with open(app_file, "w") as f:
    f.write(app)

print("Logic fixed!")
