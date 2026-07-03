import sys
import os
from kubernetes import client, config
from kubernetes.client.rest import ApiException

def main():
    # Load kubeconfig
    try:
        config.load_kube_config()
    except Exception:
        try:
            config.load_incluster_config()
        except Exception as e:
            print(f"Failed to load Kubernetes configuration: {e}")
            sys.exit(1)
        
    core_api = client.CoreV1Api()
    custom_api = client.CustomObjectsApi()
    api_client = client.ApiClient()
    
    # 1. Get all PVCs
    pvcs = core_api.list_namespaced_persistent_volume_claim("default")
    existing_pvc_names = {pvc.metadata.name for pvc in pvcs.items}
    print(f"Existing PVCs in namespace 'default': {existing_pvc_names}")
    
    # 2. Get all VMs
    vms = custom_api.list_namespaced_custom_object(
        group="kubevirt.io",
        version="v1",
        namespace="default",
        plural="virtualmachines"
    )
    
    for vm in vms.get("items", []):
        vm_name = vm["metadata"]["name"]
        print(f"\nChecking VM: {vm_name}")
        
        spec = vm.get("spec", {})
        template_spec = spec.get("template", {}).get("spec", {})
        volumes = template_spec.get("volumes", [])
        
        volumes_to_remove = []
        for vol in volumes:
            pvc_spec = vol.get("persistentVolumeClaim")
            if pvc_spec:
                claim_name = pvc_spec.get("claimName")
                if claim_name and claim_name not in existing_pvc_names:
                    print(f"Found non-existent PVC: '{claim_name}' in volume '{vol['name']}'")
                    volumes_to_remove.append(vol["name"])
        
        if not volumes_to_remove:
            print("No stuck/missing volumes found.")
            continue
            
        for vol_name in volumes_to_remove:
            print(f"Removing stuck volume '{vol_name}' from VM '{vm_name}'...")
            path = f"/apis/subresources.kubevirt.io/v1/namespaces/default/virtualmachines/{vm_name}/removevolume"
            body = {"name": vol_name}
            try:
                api_client.call_api(
                    resource_path=path,
                    method="PUT",
                    header_params={"Content-Type": "application/json"},
                    body=body,
                    auth_settings=["BearerToken"]
                )
                print(f"Successfully sent removevolume for '{vol_name}'")
            except ApiException as e:
                print(f"Failed to remove volume '{vol_name}': {e.body or e}")

if __name__ == "__main__":
    main()
