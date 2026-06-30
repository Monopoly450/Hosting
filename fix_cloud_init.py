import sys

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# 1. Update runcmd_yaml definition for Bitrix
old_bitrix_logic = """    # Специфично для Bitrix
    runcmd_yaml = ""
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            if packages_yaml:
                packages_yaml += "\\n  - wget"
            else:
                packages_yaml = "\\npackages:\\n  - wget"
        runcmd_yaml = "\\nruncmd:\\n  - [ wget, \\"http://repos.1c-bitrix.ru/yum/bitrix-env.sh\\" ]\\n  - [ chmod, \\"+x\\", \\"bitrix-env.sh\\" ]\\n  - [ ./bitrix-env.sh, \\"-s\\", \\"-p\\", \\"-H\\", req.name ]\\n"
"""
new_bitrix_logic = """    # Специфично для Bitrix
    runcmd_yaml = ""
    if req.os_type == "bitrix":
        if "wget" not in packages_yaml:
            if packages_yaml:
                packages_yaml += "\\n  - wget"
            else:
                packages_yaml = "\\npackages:\\n  - wget"
        runcmd_yaml = "\\n  - wget http://repos.1c-bitrix.ru/yum/bitrix-env.sh\\n  - chmod +x bitrix-env.sh\\n  - ./bitrix-env.sh -s -p -H " + req.name + "\\n"
"""
app = app.replace(old_bitrix_logic, new_bitrix_logic)

# 2. Update cloudInitNoCloud userData
import re
# We need to replace everything from "userData": f"""#cloud-config to """
pattern = r'"userData": f"""#cloud-config.*?"""'

new_userdata = '''"userData": f"""#cloud-config
ssh_pwauth: True
disable_root: false
chpasswd:
  list: |
    root:{password}
    {default_user}:{password}
  expire: False
users:
  - default
  - name: root
    lock_passwd: false
  - name: {default_user}
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    shell: /bin/bash
    lock_passwd: false
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
"""'''

app = re.sub(pattern, new_userdata, app, flags=re.DOTALL)

with open(app_file, "w") as f:
    f.write(app)

print("Cloud init fixed")
