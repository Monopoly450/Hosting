import hashlib
import sys
from kubernetes import client, config

def generate_mac_address_cluster(name: str) -> str:
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    # Prefix 02:00:01 ensures it is locally administered and doesn't conflict
    return f"02:00:01:{h[0:2]}:{h[2:4]}:{h[4:6]}"

def main():
    try:
        config.load_kube_config()
    except Exception:
        try:
            config.load_incluster_config()
        except Exception as e:
            print(f"Error loading kube config: {e}")
            sys.exit(1)

    custom_api = client.CustomObjectsApi()
    
    try:
        vms = custom_api.list_namespaced_custom_object(
            group="kubevirt.io",
            version="v1",
            namespace="default",
            plural="virtualmachines"
        )
    except Exception as e:
        print(f"Error listing VirtualMachines: {e}")
        sys.exit(1)

    patched_any = False
    for vm in vms.get("items", []):
        name = vm["metadata"]["name"]
        
        # We only care about the cluster VMs: promos-1, proxmox-2, truenas
        if name not in ["promos-1", "proxmox-2", "truenas"]:
            continue
            
        spec = vm.get("spec", {}).get("template", {}).get("spec", {})
        interfaces = spec.get("domain", {}).get("devices", {}).get("interfaces", [])
        
        idx = None
        for i, interface in enumerate(interfaces):
            if interface.get("name") == "cluster-net":
                idx = i
                break
                
        if idx is not None:
            # Check if MAC address is already present
            existing_mac = interfaces[idx].get("macAddress")
            expected_mac = generate_mac_address_cluster(name)
            
            if existing_mac == expected_mac:
                print(f"VM {name} already has correct static MAC: {existing_mac}. Skipping.")
                continue
                
            print(f"Patching VM {name} cluster-net interface (index {idx}) with static MAC: {expected_mac}...")
            
            interfaces[idx]["macAddress"] = expected_mac
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "domain": {
                                "devices": {
                                    "interfaces": interfaces
                                }
                            }
                        }
                    }
                }
            }
            
            try:
                custom_api.patch_namespaced_custom_object(
                    group="kubevirt.io",
                    version="v1",
                    namespace="default",
                    plural="virtualmachines",
                    name=name,
                    body=patch
                )
                print(f"VM {name} successfully patched.")
                patched_any = True
            except Exception as e:
                print(f"Failed to patch VM {name}: {e}")
        else:
            print(f"VM {name} does not have a cluster-net interface configured. Skipping.")

    if patched_any:
        print("\nAll cluster VMs have been patched. Please STOP and START the VMs via the Aegis Panel to apply the changes.")
    else:
        print("\nNo VMs needed patching or all VMs are already up to date.")

if __name__ == "__main__":
    main()
