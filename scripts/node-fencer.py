#!/usr/bin/env python3
import subprocess
import json
import time
import sys

def run_cmd(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(res.stderr.strip())
    return res.stdout.strip()

def get_nodes():
    try:
        out = run_cmd(["kubectl", "get", "nodes", "-o", "json"])
        data = json.loads(out)
        return data.get("items", [])
    except Exception as e:
        print(f"Error getting nodes: {e}", file=sys.stderr, flush=True)
        return []

def main():
    print("Aegis Node Fencing Daemon started.", flush=True)
    # Отслеживаем время нахождения ноды в статусе NotReady
    not_ready_nodes = {}
    
    while True:
        nodes = get_nodes()
        
        for node in nodes:
            name = node["metadata"]["name"]
            
            # Пропускаем управляющие ноды (master/control-plane), чтобы случайно не заблокировать сам мастер
            labels = node["metadata"].get("labels", {})
            is_master = any("control-plane" in label or "master" in label for label in labels)
            if is_master:
                continue
                
            # Проверяем статус Ready
            is_ready = False
            for cond in node["status"].get("conditions", []):
                if cond["type"] == "Ready":
                    if cond["status"] == "True":
                        is_ready = True
                    break
            
            # Проверяем наличие тейнта out-of-service
            taints = node["spec"].get("taints", [])
            has_out_of_service = any(t.get("key") == "node.kubernetes.io/out-of-service" for t in taints)
            
            if not is_ready:
                # Нода не готова
                if name not in not_ready_nodes:
                    not_ready_nodes[name] = time.time()
                    print(f"Node {name} is NotReady. Starting 60s failover grace timer...", flush=True)
                else:
                    duration = time.time() - not_ready_nodes[name]
                    # Если нода лежит больше 60 секунд и тейнт еще не наложен
                    if duration >= 60.0 and not has_out_of_service:
                        print(f"Node {name} is offline for {int(duration)}s. Automatically applying out-of-service taint...", flush=True)
                        try:
                            run_cmd(["kubectl", "taint", "nodes", name, "node.kubernetes.io/out-of-service=nodeshutdown:NoExecute", "--overwrite"])
                            print(f"Successfully tainted {name}.", flush=True)
                        except Exception as e:
                            print(f"Failed to taint node {name}: {e}", file=sys.stderr, flush=True)
            else:
                # Нода здорова и готова к работе
                if name in not_ready_nodes:
                    del not_ready_nodes[name]
                    print(f"Node {name} is back online (Ready).", flush=True)
                
                # Если нода вернулась в сеть, но на ней висит тейнт — автоматически снимаем его
                if has_out_of_service:
                    print(f"Node {name} is Ready but has out-of-service taint. Automatically clearing taint...", flush=True)
                    try:
                        run_cmd(["kubectl", "taint", "nodes", name, "node.kubernetes.io/out-of-service-"])
                        print(f"Successfully cleared taint on {name}.", flush=True)
                    except Exception as e:
                        print(f"Failed to clear taint on {name}: {e}", file=sys.stderr, flush=True)
                        
        time.sleep(5)

if __name__ == "__main__":
    main()
