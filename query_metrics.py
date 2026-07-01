import urllib.request
import json

queries = [
    'sum(rate(container_fs_reads_bytes_total{container="compute",pod=~"virt-launcher-.*"}[2m])) by (pod)',
    'sum(rate(container_fs_writes_bytes_total{container="compute",pod=~"virt-launcher-.*"}[2m])) by (pod)',
    'sum(rate(container_fs_reads_total{container="compute",pod=~"virt-launcher-.*"}[2m])) by (pod)',
    'sum(rate(container_fs_writes_total{container="compute",pod=~"virt-launcher-.*"}[2m])) by (pod)'
]

for q in queries:
    print(f"--- QUERY: {q} ---")
    try:
        url = f"http://10.43.232.169:9090/api/v1/query?query={urllib.parse.quote(q)}"
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read().decode())
        results = data.get("data", {}).get("result", [])
        print("Count:", len(results))
        if results:
            print("First result:")
            print(json.dumps(results[0], indent=2))
    except Exception as e:
        print("Error:", e)
