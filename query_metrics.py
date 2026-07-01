import urllib.request
import json

queries = [
    "kubevirt_vmi_storage_read_traffic_bytes_total",
    "kubevirt_vmi_storage_read_iops_total"
]

for q in queries:
    print(f"--- QUERY: {q} ---")
    try:
        url = f"http://10.43.232.169:9090/api/v1/query?query={q}"
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read().decode())
        results = data.get("data", {}).get("result", [])
        print("Count:", len(results))
        if results:
            print("First result:")
            print(json.dumps(results[0], indent=2))
    except Exception as e:
        print("Error:", e)
