#!/usr/bin/env bash

echo "=== 1. Virtual Machines (VMs) ==="
kubectl get vm -o wide

echo "=== 2. Virtual Machine Instances (VMIs) ==="
kubectl get vmi -o wide

echo "=== 3. DataVolumes (DVs) ==="
kubectl get dv -o wide

echo "=== 4. PersistentVolumeClaims (PVCs) ==="
kubectl get pvc -o wide

echo "=== 5. All Pods in Default Namespace ==="
kubectl get pods -o wide

echo "=== 6. Pods in CDI Namespace ==="
kubectl get pods -n cdi -o wide

echo "=== 7. Recent Scheduler and KubeVirt Events ==="
kubectl get events --sort-by='.metadata.creationTimestamp' | tail -n 25

echo "=== 8. Detailed status of all pending pods ==="
for pod in $(kubectl get pods --field-selector=status.phase=Pending -o jsonpath='{.items[*].metadata.name}'); do
    echo "--- Pod: $pod ---"
    kubectl describe pod $pod | grep -A 10 Events
done
