import re

app_file = "backend/app/api/host.py"
with open(app_file, "r") as f:
    app = f.read()

replacement = """
            "os_info": node.status.node_info.os_image,
            "kernel_version": node.status.node_info.kernel_version,
            "kubelet_version": node.status.node_info.kubelet_version,
            "container_runtime": node.status.node_info.container_runtime_version,
            "architecture": node.status.node_info.architecture,
            "operating_system": node.status.node_info.operating_system,
            "system_uuid": node.status.node_info.system_uuid
"""

app = app.replace("""
            "os_info": node.status.node_info.os_image,
            "kernel_version": node.status.node_info.kernel_version,
            "kubelet_version": node.status.node_info.kubelet_version
""", replacement)

with open(app_file, "w") as f:
    f.write(app)
print("Updated API!")
