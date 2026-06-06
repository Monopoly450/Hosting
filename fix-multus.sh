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

echo "[INFO] Проверка и установка недостающих CNI плагинов (macvlan и др.)..."
CNI_VERSION="v1.5.1"
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; fi
if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi

mkdir -p /tmp/cni-plugins
curl -sSL "https://github.com/containernetworking/plugins/releases/download/${CNI_VERSION}/cni-plugins-linux-${ARCH}-${CNI_VERSION}.tgz" | tar -xz -C /tmp/cni-plugins
mkdir -p /var/lib/rancher/k3s/data/cni /var/lib/rancher/k3s/data/current/bin
cp -n /tmp/cni-plugins/* /var/lib/rancher/k3s/data/cni/ 2>/dev/null || true
cp -n /tmp/cni-plugins/* /var/lib/rancher/k3s/data/current/bin/ 2>/dev/null || true
chmod +x /var/lib/rancher/k3s/data/cni/* /var/lib/rancher/k3s/data/current/bin/* 2>/dev/null || true
rm -rf /tmp/cni-plugins

echo "[INFO] Скачивание и патчинг манифеста Multus CNI..."
curl -sL https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml | \
sed "s|/etc/cni/net.d|${CNI_CONF_DIR}|g" | \
sed "s|/opt/cni/bin|${CNI_BIN_DIR}|g" | \
sed "s|mountPath: ${CNI_CONF_DIR}/multus.d|mountPath: /etc/cni/net.d/multus.d|g" | \
sed "s|\"socketDir\": \"/host/run/multus/\"|\"socketDir\": \"/host/run/multus/\", \"binDir\": \"${CNI_BIN_DIR}\"|g" | \
sed "s|path: ${CNI_BIN_DIR}|path: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: ${CNI_BIN_DIR}|mountPath: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: /host${CNI_BIN_DIR}|mountPath: /host/var/lib/rancher/k3s/data|g" > /tmp/multus-k3s.yml

echo "[INFO] Применение пропатченного манифеста Multus в Kubernetes..."
kubectl apply -f /tmp/multus-k3s.yml
rm -f /tmp/multus-k3s.yml

echo "[INFO] Ожидание перезапуска подов Multus CNI..."
kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s

echo "[INFO] Проверка статуса подов в kube-system..."
kubectl get pods -n kube-system -l name=multus

echo "[INFO] Готово! Multus CNI настроен под пути K3s."
