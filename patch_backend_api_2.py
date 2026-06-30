import re

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# Make generate_ubuntu_manifest manipulate the dict
# Replace the return literal with building the dict, then returning it.

start_return = app.find('    return {\n        "apiVersion": "kubevirt.io/v1",')
end_manifest = app.find('def generate_windows_manifest(req: VMCreationRequest) -> dict:')

if start_return != -1 and end_manifest != -1:
    old_return_block = app[start_return:end_manifest]
    
    new_block = old_return_block.replace('    return {', '    manifest = {')
    
    inject = """
    # Инжектим дополнительные диски (PVC)
    if extra_disks:
        manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"].extend(extra_disks)
        manifest["spec"]["template"]["spec"]["volumes"].extend(extra_volumes)
        
    return manifest

"""
    new_block = new_block.rstrip() + inject
    
    app = app[:start_return] + new_block + app[end_manifest:]
    with open(app_file, "w") as f:
        f.write(app)
    print("Backend API fully patched.")
else:
    print("Could not find the return block")
