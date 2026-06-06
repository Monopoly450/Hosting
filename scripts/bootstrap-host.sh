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
fi

# 3. Определение активного сетевого интерфейса
log "Определение активного сетевого интерфейса..."
ACTIVE_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$ACTIVE_IFACE" ]; then
    error "Не удалось определить активный сетевой интерфейс."
fi
log "Активный сетевой интерфейс хоста: $ACTIVE_IFACE"

# 4. Установка зависимостей
log "Установка необходимых пакетов (curl, iptables, bridge-utils)..."
apt-get update
apt-get install -y curl iptables bridge-utils jq net-tools openssl

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
mkdir -p $HOME/.kube
cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
chown -R $SUDO_USER:$SUDO_USER $HOME/.kube || true
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Ждем запуска node
log "Ожидание готовности ноды Kubernetes..."
until kubectl get nodes | grep -q "Ready"; do
    sleep 3
done
log "Kubernetes нода готова!"

# 6. Установка Multus CNI
log "Установка Multus CNI (поддержка дополнительных сетевых интерфейсов)..."
kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml

# Ждем запуска Multus
log "Ожидание запуска Multus CNI..."
kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s

# 7. Создание NetworkAttachmentDefinition для Macvlan (Мост в домашнюю сеть)
log "Создание NetworkAttachmentDefinition (сетевой мост в домашнюю сеть)..."
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
      "type": "macvlan",
      "master": "${ACTIVE_IFACE}",
      "mode": "bridge",
      "ipam": {}
    }'
EOF
log "Сетевой мост bridge-network успешно создан на базе интерфейса ${ACTIVE_IFACE}!"

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

# Если KVM не поддерживается процессором в VMware, включаем программную эмуляцию
if [ "$KVM_SUPPORTED" = false ]; then
    log "Настройка KubeVirt для работы в режиме эмуляции (без KVM)..."
    kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}'
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

log "=========================================================="
log "Установка завершена! Kubernetes + KubeVirt + CDI развернуты."
log "Проверьте статус подов: kubectl get pods -A"
log "Панель управления можно запускать и подключать к /etc/rancher/k3s/k3s.yaml"
log "=========================================================="
