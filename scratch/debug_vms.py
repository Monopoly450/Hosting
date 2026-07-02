import sys
import os
import traceback

# Add backend to path
sys.path.append("/app")

print("--- DEBUG START ---")
try:
    from app.core.k8s_client import K8sClient
    client = K8sClient()
    print("K8sClient initialized successfully.")
except Exception as e:
    print(f"Error initializing K8sClient: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("Calling client.list_vms()...")
    vms = client.list_vms()
    print(f"Number of VMs returned from K8s: {len(vms)}")
    for i, vm in enumerate(vms):
        print(f"  [{i}] VM Name: {vm.get('name')}, Status: {vm.get('status')}, CPU: {vm.get('cpu_cores')}, RAM: {vm.get('memory')}")
except Exception as e:
    print(f"Error listing VMs from K8s: {e}")
    traceback.print_exc()

try:
    from app.db import SessionLocal
    from app.models.models import VMTask
    db = SessionLocal()
    db_vms = db.query(VMTask).all()
    print(f"Number of VMTasks in DB: {len(db_vms)}")
    for vm in db_vms:
         print(f"  DB VM: {vm.name}, Status: {vm.status}, CPU: {vm.cpu_cores}, RAM: {vm.memory_gb}, Disk: {vm.disk_gb}")
    db.close()
except Exception as e:
    print(f"Error querying DB: {e}")
    traceback.print_exc()

print("--- DEBUG END ---")
