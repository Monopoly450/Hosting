#!/usr/bin/env bash

echo "=== 1. DataVolume Status ==="
kubectl get dv mama-disk -o yaml || echo "DataVolume not found"

echo "=== 2. PVC Status ==="
kubectl get pvc mama-disk -o yaml || echo "PVC not found"

echo "=== 3. PVC Description (Events) ==="
kubectl describe pvc mama-disk || echo "Error describing PVC"

echo "=== 4. CDI Importer Pods in default namespace ==="
kubectl get pods -n default -l cdi.kubevirt.io/storage.import.importPvcName=mama-disk -o wide || echo "No importer pods found"

echo "=== 5. CDI Operator & Controller Pods Status ==="
kubectl get pods -n cdi -o wide || echo "Failed to get cdi pods"

echo "=== 6. CDI Operator Logs ==="
kubectl logs -n cdi -l app=cdi-operator --tail=50 || echo "Failed to get cdi-operator logs"
