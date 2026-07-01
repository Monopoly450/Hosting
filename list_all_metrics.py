import urllib.request
import json

try:
    url = "http://10.43.232.169:9090/api/v1/label/__name__/values"
    resp = urllib.request.urlopen(url, timeout=5)
    data = json.loads(resp.read().decode())
    names = data.get("data", [])
    print("Total metrics:", len(names))
    
    kubevirt_names = [n for n in names if "kubevirt" in n]
    print("Kubevirt metrics:", len(kubevirt_names))
    for n in kubevirt_names[:20]:
        print("  ", n)
        
    storage_names = [n for n in names if "storage" in n or "io" in n or "disk" in n]
    print("Storage/disk metrics:", len(storage_names))
    for n in storage_names[:20]:
        print("  ", n)
except Exception as e:
    print("Error:", e)
