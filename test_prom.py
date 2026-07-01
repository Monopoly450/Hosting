import urllib.request
import json
try:
    resp = urllib.request.urlopen("http://10.43.232.169:9090/api/v1/query?query=container_cpu_usage_seconds_total", timeout=5)
    data = json.loads(resp.read().decode())
    print("STATUS:", data.get("status"))
    print("RESULTS COUNT:", len(data.get("data", {}).get("result", [])))
    if data.get("data", {}).get("result"):
         # print first 3 result names
         results = data.get("data", {}).get("result")
         print("SAMPLES:")
         for r in results[:3]:
             print("  Pod:", r.get("metric", {}).get("pod"), "Container:", r.get("metric", {}).get("container"))
except Exception as e:
    print("ERROR:", e)
