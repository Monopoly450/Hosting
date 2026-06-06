#!/usr/bin/env bash

# Скрипт для исправления Multus CNI на K3s
set -e

echo "[INFO] Определение путей CNI в K3s..."
CNI_CONF_DIR="/var/lib/rancher/k3s/agent/etc/cni/net.d"
CNI_BIN_DIR="/var/lib/rancher/k3s/data/cni"

if [ ! -d "$CNI_BIN_DIR" ]; then
    CNI_BIN_DIR="/var/lib/rancher/k3s/data/current/bin"
fi

echo "[INFO] Используемые пути:"
echo "  - Конфигурации CNI: ${CNI_CONF_DIR}"
echo "  - Бинарники CNI: ${CNI_BIN_DIR}"

echo "[INFO] Скачивание и патчинг манифеста Multus CNI..."
curl -sL https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml | \
sed "s|/etc/cni/net.d|${CNI_CONF_DIR}|g" | \
sed "s|/opt/cni/bin|${CNI_BIN_DIR}|g" > /tmp/multus-k3s.yml

echo "[INFO] Применение пропатченного манифеста Multus в Kubernetes..."
kubectl apply -f /tmp/multus-k3s.yml
rm -f /tmp/multus-k3s.yml

echo "[INFO] Ожидание перезапуска подов Multus CNI..."
kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s

echo "[INFO] Проверка статуса подов в kube-system..."
kubectl get pods -n kube-system -l name=multus

echo "[INFO] Готово! Multus CNI настроен под пути K3s."
