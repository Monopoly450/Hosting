import urllib.request
import json

try:
    url = "http://10.43.232.169:9090/api/v1/query?query=container_cpu_usage_seconds_total"
    resp = urllib.request.urlopen(url, timeout=5)
    data = json.loads(resp.read().decode())
    results = data.get("data", {}).get("result", [])
    print("Total results for container_cpu_usage_seconds_total:", len(results))
    if results:
        # Print labels for the first 5 results that are virt-launcher pods
        launcher_results = [r for r in results if "virt-launcher" in r.get("metric", {}).get("pod", "")]
        print("Launcher results count:", len(launcher_results))
        for r in launcher_results[:5]:
            print(json.dumps(r["metric"], indent=2))
except Exception as e:
    print("Error:", e)
