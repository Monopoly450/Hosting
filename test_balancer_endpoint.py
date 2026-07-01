import urllib.request
import json

try:
    # Query the local backend inside the docker container by connecting via localhost on port 8000 (which is the backend port)
    url = "http://localhost:8000/api/vms/balancer/resources"
    resp = urllib.request.urlopen(url, timeout=5)
    data = json.loads(resp.read().decode())
    print("BALANCER RESOURCES ENDPOINT RESPONSE:")
    print(json.dumps(data, indent=2))
except Exception as e:
    print("Error querying balancer endpoint:", e)
