#!/usr/bin/env bash

# Скрипт авто-настройки хоста для KubeVirt хостинга
# Должен запускаться на целевой Ubuntu машине под root или через sudo

set -e

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

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

# 1. Проверка прав root
if [ "$EUID" -ne 0 ]; then
    error "Этот скрипт должен быть запущен с правами root (через sudo)."
fi

# 2. Проверка аппаратной виртуализации (KVM)
log "Проверка поддержки KVM..."
KVM_SUPPORTED=true
if [ ! -e /dev/kvm ]; then
    warn "Устройство /dev/kvm не найдено! Аппаратная виртуализация выключена."
    warn "Убедитесь, что в настройках процессора виртуалки VMware включена галочка 'Virtualize Intel VT-x/EPT or AMD-V/RVI'."
    warn "KubeVirt будет настроен в режиме программной эмуляции (будет медленно)."
    KVM_SUPPORTED=false
else
    log "Аппаратная виртуализация KVM поддерживается и доступна."
    chmod 666 /dev/kvm
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' > /etc/udev/rules.d/99-kvm.rules
    udevadm control --reload-rules && udevadm trigger || true
fi

# 2b. Включение вложенной виртуализации (Nested Virtualization)
# Нужно, чтобы ВНУТРИ гостевых ВМ работал /dev/kvm — например, для Proxmox VE,
# который сам запускает виртуалки. Работает только на bare-metal хосте
# (если сам сервер уже виртуалка, вложенность может не завестись).
if [ "$KVM_SUPPORTED" = true ]; then
    log "Настройка вложенной виртуализации (nested)..."
    if grep -q vmx /proc/cpuinfo; then
        NESTED_MOD="kvm_intel"
        echo "options kvm_intel nested=1" > /etc/modprobe.d/kvm-nested.conf
    elif grep -q svm /proc/cpuinfo; then
        NESTED_MOD="kvm_amd"
        echo "options kvm_amd nested=1" > /etc/modprobe.d/kvm-nested.conf
    else
        NESTED_MOD=""
        warn "CPU не сообщает о поддержке vmx/svm — вложенная виртуализация недоступна."
    fi

    if [ -n "$NESTED_MOD" ]; then
        # Пытаемся включить на лету (может потребовать выгрузки модуля, если он занят)
        echo Y > "/sys/module/${NESTED_MOD}/parameters/nested" 2>/dev/null || \
            modprobe -r "$NESTED_MOD" 2>/dev/null && modprobe "$NESTED_MOD" nested=1 2>/dev/null || true
        NESTED_STATE=$(cat "/sys/module/${NESTED_MOD}/parameters/nested" 2>/dev/null || echo "?")
        if [ "$NESTED_STATE" = "Y" ] || [ "$NESTED_STATE" = "1" ]; then
            log "Вложенная виртуализация ВКЛЮЧЕНА (${NESTED_MOD}). Proxmox сможет запускать свои ВМ."
        else
            warn "Вложенная виртуализация прописана в /etc/modprobe.d, но не активна (${NESTED_STATE})."
            warn "Модуль ${NESTED_MOD} занят. Чтобы применить, перезагрузите сервер: sudo reboot"
        fi
    fi
fi

# 3. Определение активного сетевого интерфейса
log "Определение активного сетевого интерфейса..."
ACTIVE_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$ACTIVE_IFACE" ]; then
    error "Не удалось определить активный сетевой интерфейс."
fi
log "Активный сетевой интерфейс хоста: $ACTIVE_IFACE"

# 4. Установка зависимостей
log "Установка необходимых пакетов (curl, iptables, bridge-utils, docker, nginx, fail2ban)..."
apt-get update
apt-get install -y curl iptables bridge-utils jq net-tools openssl nginx fail2ban

# Nginx нужен только как балансировщик (/etc/nginx/conf.d/aegis_balancer_*.conf).
# Его дефолтный сайт занимает порт 80, а он требуется прокси Caddy для своих
# доменов: по 80 идёт HTTP-01 проверка Let's Encrypt и редирект на HTTPS.
# Поэтому дефолтный сайт отключаем, сам nginx оставляем работать.
if [ -e /etc/nginx/sites-enabled/default ]; then
    log "Отключение дефолтного сайта nginx (порт 80 нужен Caddy для TLS-сертификатов)..."
    rm -f /etc/nginx/sites-enabled/default
    nginx -t &>/dev/null && systemctl reload nginx || true
fi

# Установка Docker и Docker Compose v2 для запуска панели
log "Проверка и установка Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
    apt-get install -y docker.io docker-compose-v2
    systemctl enable --now docker
    log "Docker и Docker Compose успешно установлены!"
else
    log "Docker уже установлен в системе."
fi

# Установка MinIO Client (mc) для администрирования S3 хранилища
log "Проверка и установка MinIO Client (mc)..."
if ! command -v mc &> /dev/null; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; fi
    if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi
    curl -sSL "https://dl.min.io/client/mc/release/linux-${ARCH}/mc" -o /usr/local/bin/mc
    chmod +x /usr/local/bin/mc
    log "MinIO Client (mc) успешно установлен!"
else
    log "MinIO Client (mc) уже установлен в системе."
fi

# 5. Установка K3s (Kubernetes)
log "Установка K3s (легковесный Kubernetes)..."
if ! command -v k3s &> /dev/null; then
    # Отключаем traefik и servicelb, так как нам нужна чистая среда виртуализации
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -
    log "K3s успешно установлен!"
else
    log "K3s уже установлен."
fi

# Настройка kubeconfig для пользователя
log "Настройка прав доступа к Kubernetes API (kubeconfig)..."
mkdir -p /root/.kube
cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
chmod 600 /root/.kube/config
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    SUDO_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    if [ -d "$SUDO_HOME" ]; then
        mkdir -p "$SUDO_HOME/.kube"
        cp /etc/rancher/k3s/k3s.yaml "$SUDO_HOME/.kube/config"
        chown -R "$SUDO_USER:$SUDO_USER" "$SUDO_HOME/.kube"
        chmod 600 "$SUDO_HOME/.kube/config"
        log "kubeconfig успешно скопирован в домашнюю директорию пользователя $SUDO_USER ($SUDO_HOME/.kube/config)"
    fi
fi

# Ждем запуска node
log "Ожидание готовности ноды Kubernetes..."
until kubectl get nodes | grep -q "Ready"; do
    sleep 3
done
log "Kubernetes нода готова!"

# 6. Установка Multus CNI
log "Установка Multus CNI (поддержка дополнительных сетевых интерфейсов)..."
log "Определение путей CNI в K3s..."
CNI_CONF_DIR="/var/lib/rancher/k3s/agent/etc/cni/net.d"
CNI_BIN_DIR="/var/lib/rancher/k3s/data/cni"

if [ ! -d "$CNI_BIN_DIR" ]; then
    CNI_BIN_DIR="/var/lib/rancher/k3s/data/current/bin"
fi

log "Используемые пути для Multus:"
log "  - Конфигурации CNI: ${CNI_CONF_DIR}"
log "  - Бинарники CNI: ${CNI_BIN_DIR}"

log "Проверка и установка недостающих CNI плагинов (macvlan и др.)..."
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

log "Скачивание и патчинг манифеста Multus CNI..."
MULTUS_URL="https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml"
MULTUS_FALLBACK_URL="https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.0.2/deployments/multus-daemonset-thick.yml"

# Попытка скачать манифест
if ! curl -sSfL "$MULTUS_URL" > /tmp/multus-raw.yml; then
    warn "Не удалось скачать свежий манифест Multus с master ветки. Попытка скачать стабильную версию v4.0.2..."
    if ! curl -sSfL "$MULTUS_FALLBACK_URL" > /tmp/multus-raw.yml; then
        error "Не удалось загрузить манифест Multus CNI. Проверьте интернет-соединение с raw.githubusercontent.com."
    fi
fi

cat /tmp/multus-raw.yml | \
sed "s|/etc/cni/net.d|${CNI_CONF_DIR}|g" | \
sed "s|/opt/cni/bin|${CNI_BIN_DIR}|g" | \
sed "s|mountPath: ${CNI_CONF_DIR}/multus.d|mountPath: /etc/cni/net.d/multus.d|g" | \
sed "s|\"socketDir\": \"/host/run/multus/\"|\"socketDir\": \"/host/run/multus/\", \"binDir\": \"${CNI_BIN_DIR}\"|g" | \
sed "s|path: ${CNI_BIN_DIR}|path: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: ${CNI_BIN_DIR}|mountPath: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: /host${CNI_BIN_DIR}|mountPath: /host/var/lib/rancher/k3s/data|g" > /tmp/multus-k3s.yml

if [ ! -s /tmp/multus-k3s.yml ]; then
    error "Созданный манифест Multus CNI пуст. Сбой патчинга."
fi

kubectl apply -f /tmp/multus-k3s.yml
rm -f /tmp/multus-raw.yml /tmp/multus-k3s.yml

log "Патчинг лимитов ресурсов для Multus CNI (увеличиваем memory limit до 500Mi)..."
kubectl patch daemonset kube-multus-ds -n kube-system --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"kube-multus","resources":{"limits":{"memory":"500Mi"},"requests":{"memory":"100Mi"}}}]}}}}' || true

# Ждем запуска Multus
log "Ожидание запуска Multus CNI..."
kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s

# 7. Создание NetworkAttachmentDefinition для виртуальных машин (Bridge / NAT)
log "Ожидание готовности CRD NetworkAttachmentDefinition от Multus..."
for i in {1..30}; do
    if kubectl get crd network-attachment-definitions.k8s.cni.cncf.io &>/dev/null; then
        log "CRD NetworkAttachmentDefinition успешно зарегистрирован!"
        break
    fi
    log "Ожидание регистрации CRD NetworkAttachmentDefinition... ($i/30)"
    sleep 5
done

# Сетевой режим: Принудительный NAT / Masquerade
log "Настройка сети в режиме NAT / Masquerade на мосту br-vms (Изолированная сеть 172.20.0.0/24)..."

# 1. Создание моста br-vms
if ! ip link show br-vms &>/dev/null; then
    ip link add br-vms type bridge
    ip addr add 172.20.0.1/24 dev br-vms
    ip link set br-vms up
fi

# 2. Включение IP Forwarding
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-ip-forward.conf

# 2.5. Оптимизация дискового кэша для HDD (предотвращение зависаний I/O при импорте ВМ)
log "Настройка параметров sysctl для стабильности HDD..."
sysctl -w vm.dirty_background_ratio=5
sysctl -w vm.dirty_ratio=10
cat <<EOF > /etc/sysctl.d/99-aegis-hdd-tuning.conf
vm.dirty_background_ratio=5
vm.dirty_ratio=10
EOF

# 3. Настройка IPTables правил
iptables -t nat -C POSTROUTING -s 172.20.0.0/24 -o "${ACTIVE_IFACE}" -j MASQUERADE &>/dev/null || \
    iptables -t nat -A POSTROUTING -s 172.20.0.0/24 -o "${ACTIVE_IFACE}" -j MASQUERADE
iptables -C FORWARD -i br-vms -j ACCEPT &>/dev/null || \
    iptables -A FORWARD -i br-vms -j ACCEPT
iptables -C FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT &>/dev/null || \
    iptables -A FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT

# 4. Сохранение правил iptables
if dpkg -l | grep -q iptables-persistent; then
    netfilter-persistent save
else
    log "Установка iptables-persistent..."
    echo iptables-persistent iptables-persistent/italy select false | debconf-set-selections
    echo iptables-persistent iptables-persistent/sec select false | debconf-set-selections
    DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
    netfilter-persistent save
fi

# 5. Установка и настройка dnsmasq
log "Установка и настройка DHCP (dnsmasq) на интерфейсе br-vms..."
apt-get update && apt-get install -y dnsmasq
cat <<EOF > /etc/dnsmasq.d/aegis-dhcp.conf
interface=br-vms
bind-interfaces
dhcp-range=172.20.0.10,172.20.0.250,12h
dhcp-option=option:router,172.20.0.1
dhcp-option=option:dns-server,8.8.8.8,1.1.1.1
EOF
systemctl restart dnsmasq

# 6. Создание NetworkAttachmentDefinition типа bridge БЕЗ IPAM.
# IP не назначается CNI — каждая ВМ прописывает свой СТАТИЧЕСКИЙ адрес (172.20.0.x)
# через cloud-init. Так адрес стабилен и не меняется при перезагрузке ВМ.
cat <<EOF | kubectl apply -f -
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: bridge-network
  namespace: default
spec:
  config: '{
      "cniVersion": "0.3.1",
      "name": "bridge-network",
      "type": "bridge",
      "bridge": "br-vms",
      "isGateway": false,
      "ipam": {}
  }'
EOF
log "Сетевой мост bridge-network настроен (статические IP через cloud-init)!"

# 7.5 Установка Kubernetes VolumeSnapshot CRDs и Snapshot Controller
log "Установка VolumeSnapshot CRDs и Snapshot Controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshotclasses.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshotcontents.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshots.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml || true

# 8. Установка KubeVirt
log "Получение актуальной версии KubeVirt..."
KUBEVIRT_VERSION=$(curl -s https://api.github.com/repos/kubevirt/kubevirt/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
if [ -z "$KUBEVIRT_VERSION" ]; then
    KUBEVIRT_VERSION="v1.2.0" # Фолбэк на стабильную версию
fi
log "Установка KubeVirt версии ${KUBEVIRT_VERSION}..."

log "Применение KubeVirt Operator..."
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"

log "Применение KubeVirt Custom Resource..."
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"

# Настройка параметров KubeVirt (включаем горячее подключение дисков HotplugVolumes, снимки WorkloadSnapshots и эмуляцию при необходимости)
log "Настройка конфигурации KubeVirt (Feature Gates)..."
if [ "$KVM_SUPPORTED" = false ]; then
    kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true,"featureGates":["HotplugVolumes","DeclarativeHotplugVolumes","WorkloadSnapshots","Snapshot"]}}}}'
else
    kubectl patch kubevirt kubevirt -n kubevirt --type=merge -p '{"spec":{"configuration":{"developerConfiguration":{"featureGates":["HotplugVolumes","DeclarativeHotplugVolumes","WorkloadSnapshots","Snapshot"]}}}}'
fi

# Ждем развертывания KubeVirt
log "Ожидание запуска компонентов KubeVirt (это может занять пару минут)..."
kubectl rollout status deployment/virt-operator -n kubevirt --timeout=180s
log "KubeVirt Operator запущен. Проверка готовности KubeVirt CR..."
# Будем опрашивать статус KubeVirt
for i in {1..30}; do
    STATUS=$(kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.status.phase}' 2>/dev/null || echo "Waiting")
    if [ "$STATUS" = "Deployed" ]; then
        log "KubeVirt успешно развернут!"
        if [ "$KVM_SUPPORTED" = false ]; then
            log "Повторное применение патча эмуляции KubeVirt..."
            kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}' || true
        fi
        break
    fi
    log "Текущий статус KubeVirt: $STATUS. Ожидание..."
    sleep 10
done

# 9. Установка CDI (Containerized Data Importer)
log "Получение актуальной версии CDI..."
CDI_VERSION=$(curl -s https://api.github.com/repos/kubevirt/containerized-data-importer/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
if [ -z "$CDI_VERSION" ]; then
    CDI_VERSION="v1.59.0" # Фолбэк
fi
log "Установка CDI версии ${CDI_VERSION}..."

log "Применение CDI Operator..."
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"

log "Применение CDI Custom Resource..."
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"

# Ожидание развертывания CDI
log "Ожидание готовности CDI..."
kubectl rollout status deployment/cdi-operator -n cdi --timeout=120s
for i in {1..30}; do
    STATUS=$(kubectl get cdi cdi -n cdi -o jsonpath='{.status.phase}' 2>/dev/null || echo "Waiting")
    if [ "$STATUS" = "Deployed" ]; then
        log "CDI успешно развернут!"
        # Настройка класса хранилища для временных дисков (scratch space)
        kubectl patch cdi cdi --type=merge --patch '{"spec": {"config": {"scratchSpaceStorageClass": "local-path"}}}' || true
        # Настройка StorageProfile 'local-path' для поддержки импорта дисков
        log "Настройка StorageProfile 'local-path'..."
        kubectl patch storageprofile local-path --type=merge -p '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}' || true
        
        # Включение расширения дисков для local-path
        log "Включение allowVolumeExpansion для StorageClass 'local-path'..."
        kubectl patch storageclass local-path -p '{"allowVolumeExpansion": true}' || true
        break
    fi
    log "Текущий статус CDI: $STATUS. Ожидание..."
    sleep 10
done

# 10. Установка утилиты virtctl
log "Установка virtctl (CLI для KubeVirt)..."
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; fi
if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi
curl -LO "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/virtctl-${KUBEVIRT_VERSION}-linux-${ARCH}"
chmod +x virtctl-${KUBEVIRT_VERSION}-linux-${ARCH}
mv virtctl-${KUBEVIRT_VERSION}-linux-${ARCH} /usr/local/bin/virtctl
log "virtctl успешно установлен!"

# 11. Установка Helm и Prometheus Stack (для сбора метрик)
log "Установка Helm..."
if ! command -v helm &> /dev/null; then
    curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
    chmod +x /tmp/get_helm.sh
    /tmp/get_helm.sh
    rm -f /tmp/get_helm.sh
    log "Helm успешно установлен!"
else
    log "Helm уже установлен."
fi

log "Установка Prometheus Stack для сбора метрик ВМ..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo update
kubectl create namespace prometheus || true
helm install prometheus prometheus-community/kube-prometheus-stack -n prometheus \
  --set grafana.enabled=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false || true
log "Prometheus Stack успешно развернут в namespace prometheus!"

# 12. Автоматическая настройка OpenEBS LVM для горячей замены
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/install-openebs-lvm.sh" ]; then
    log "Запуск настройки OpenEBS LVM для поддержки горячей замены дисков..."
    bash "${SCRIPT_DIR}/install-openebs-lvm.sh" || true
fi

# 13. Автоматическая настройка параметров безопасности хоста (Fail2Ban + права .env)
log "Настройка параметров безопасности хост-системы..."
if [ -f "${SCRIPT_DIR}/../.env" ]; then
    chmod 600 "${SCRIPT_DIR}/../.env" || true
    log "Установлены безопасные права 600 на файл конфигурации .env"
fi

JAIL_LOCAL="/etc/fail2ban/jail.local"
log "Создание конфигурации Fail2Ban: ${JAIL_LOCAL}..."
cat <<EOT > "$JAIL_LOCAL"
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
destemail = root@localhost
sender = root@localhost
action = %(action_mwl)s

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 1d
EOT

systemctl restart fail2ban || true
systemctl enable fail2ban || true
log "Служба Fail2Ban настроена и успешно запущена!"

log "=========================================================="
log "Установка завершена! Kubernetes + KubeVirt + CDI + Prometheus + Nginx + Fail2Ban развернуты."
log "Проверьте статус подов: kubectl get pods -A"
log "Панель управления можно запускать и подключать к /etc/rancher/k3s/k3s.yaml"
log "=========================================================="
