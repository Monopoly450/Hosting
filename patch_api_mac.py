import re

with open("backend/app/api/vms.py", "r") as f:
    content = f.read()

# Add hashlib and generate_mac_address
mac_func = """import secrets
import string
import hashlib

def generate_mac_address(name: str) -> str:
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    # 02:00:00 prefix ensures it's a locally administered unicast MAC
    return f"02:00:00:{h[0:2]}:{h[2:4]}:{h[4:6]}"
"""
content = content.replace("import secrets\nimport string", mac_func)

# Replace interfaces in ubuntu
ubuntu_iface_old = """                            "interfaces": [
                                {
                                    "name": "bridge-net",
                                    "bridge": {}
                                }
                            ]"""
ubuntu_iface_new = """                            "interfaces": [
                                {
                                    "name": "bridge-net",
                                    "bridge": {},
                                    "macAddress": generate_mac_address(req.name)
                                }
                            ]"""
content = content.replace(ubuntu_iface_old, ubuntu_iface_new)

with open("backend/app/api/vms.py", "w") as f:
    f.write(content)
