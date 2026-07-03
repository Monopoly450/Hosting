#!/usr/bin/env bash

# Скрипт автоматической настройки Master-ноды (node-1) для KubeVirt HA кластера
# Должен запускаться от имени root на node-1

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[INFO]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"
    exit 1
}

if [ "$EUID" -ne 0 ]; then
    error "Этот скрипт должен быть запущен с правами root (через sudo)."
fi

# 1. Проверка аппаратной виртуализации (KVM)
log "Проверка поддержки KVM..."
if [ ! -e /dev/kvm ]; then
    warn "Устройство /dev/kvm не найдено! Включите вложенную виртуализацию (Nested Virtualization) в гипервизоре."
    warn "KubeVirt будет настроен в режиме программной эмуляции (будет работать медленнее)."
    KVM_EMULATION=true
else
    log "Аппаратная виртуализация KVM поддерживается и доступна."
    chmod 666 /dev/kvm
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' > /etc/udev/rules.d/99-kvm.rules
    udevadm control --reload-rules && udevadm trigger || true
    KVM_EMULATION=false
fi

# 2. Определение активного сетевого интерфейса
log "Определение активного сетевого интерфейса..."
ACTIVE_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$ACTIVE_IFACE" ]; then
    error "Не удалось определить активный сетевой интерфейс."
fi
log "Активный интерфейс хоста: $ACTIVE_IFACE"

# 3. Установка пакетов
log "Установка необходимых утилит (nfs-common, curl, docker)..."
apt-get update
apt-get install -y curl iptables bridge-utils jq net-tools openssl nginx nfs-common

# Установка Docker и Compose
if ! command -v docker &> /dev/null; then
    apt-get install -y docker.io docker-compose-v2
    systemctl enable --now docker
else
    log "Docker уже установлен."
fi

# 4. Установка K3s Master
log "Установка K3s Master (без встроенных traefik, servicelb, local-storage)..."
if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb --disable local-storage --write-kubeconfig-mode 644" sh -
    log "K3s успешно установлен!"
else
    log "K3s уже установлен."
fi

# Настройка kubeconfig
mkdir -p /root/.kube
cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
chmod 600 /root/.kube/config
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Копируем пользователю sudo
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    SUDO_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    if [ -d "$SUDO_HOME" ]; then
        mkdir -p "$SUDO_HOME/.kube"
        cp /etc/rancher/k3s/k3s.yaml "$SUDO_HOME/.kube/config"
        chown -R "$SUDO_USER:$SUDO_USER" "$SUDO_HOME/.kube"
        chmod 600 "$SUDO_HOME/.kube/config"
    fi
fi

# Ожидание готовности Kubernetes API
log "Ожидание готовности ноды..."
until kubectl get nodes | grep -q "Ready"; do
    sleep 3
done

# 5. Установка Multus CNI
log "Установка Multus CNI..."
CNI_BIN_DIR="/var/lib/rancher/k3s/data/cni"
if [ ! -d "$CNI_BIN_DIR" ]; then
    CNI_BIN_DIR="/var/lib/rancher/k3s/data/current/bin"
fi
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

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.0.2/deployments/multus-daemonset-thick.yml

# 6. Установка Helm
log "Установка Helm..."
if ! command -v helm &> /dev/null; then
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# 7. Подключение NFS СХД через Helm
read -p "Введите IP-адрес СХД (san-storage): " SAN_IP
if [ -z "$SAN_IP" ]; then
    error "IP-адрес СХД не может быть пустым."
fi

log "Установка NFS-провайдера динамических дисков..."
helm repo add nfs-subdir-external-provisioner https://kubernetes-charts.storage.googleapis.com 2>/dev/null || \
helm repo add nfs-subdir-external-provisioner https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner/
helm repo update

# Устанавливаем NFS Provisioner как default storage class
helm install nfs-storage nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
  --set nfs.server="$SAN_IP" \
  --set nfs.path="/mnt/shared-pvc" \
  --set storageClass.name="nfs-storage" \
  --set storageClass.defaultClass=true \
  --set storageClass.reclaimPolicy=Delete

# 8. Установка KubeVirt & CDI
log "Установка KubeVirt оператора виртуализации..."
KUBEVIRT_VER=$(curl -s https://api.github.com/repos/kubevirt/kubevirt/releases/latest | jq -r .tag_name)
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VER}/kubevirt-operator.yaml"

# Настройка эмуляции при необходимости
if [ "$KVM_EMULATION" = true ]; then
    kubectl create configmap kubevirt-config -n kubevirt --from-literal=debug.useEmulation=true || \
    kubectl patch configmap kubevirt-config -n kubevirt --type merge -p '{"data":{"debug.useEmulation":"true"}}'
fi

kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VER}/kubevirt-cr.yaml"

# Включение Feature Gates (LiveMigration и Hotplug)
kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"featureGates":["LiveMigration","HotplugVolumes"]}}}}'

log "Установка Containerized Data Importer (CDI) для загрузки образов..."
CDI_VER=$(curl -s https://api.github.com/repos/kubevirt/containerized-data-importer/releases/latest | jq -r .tag_name)
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VER}/cdi-operator.yaml"
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VER}/cdi-cr.yaml"

# 9. Установка virtctl
log "Установка утилиты virtctl..."
curl -LO "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VER}/virtctl-${KUBEVIRT_VER}-linux-amd64"
install "virtctl-${KUBEVIRT_VER}-linux-amd64" /usr/local/bin/virtctl
rm "virtctl-${KUBEVIRT_VER}-linux-amd64"

# 10. Установка авто-перезагрузки (Aegis Node Fencer)
log "Настройка демона авто-перезагрузки/failover (Aegis Node Fencer)..."
SCRIPT_PATH="/root/Hosting/scripts/node-fencer.py"
chmod +x "$SCRIPT_PATH"

tee /etc/systemd/system/aegis-fencer.service > /dev/null <<EOF
[Unit]
Description=Aegis Node Fencing Daemon
After=network.target

[Service]
ExecStart=/usr/bin/python3 $SCRIPT_PATH
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aegis-fencer

log "--------------------------------------------------------"
log "Установка Master-ноды (node-1) завершена!"
log "Ваш K3S Join Token для подключения node-2:"
echo -e "${YELLOW}$(cat /var/lib/rancher/k3s/server/node-token)${NC}"
log "Запустите скрипт bootstrap-cluster-node2.sh на node-2, используя этот токен."
log "--------------------------------------------------------"
