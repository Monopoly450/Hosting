#!/usr/bin/env bash
#
# Единый установщик ByteBurners Hosting (Aegis).
# Запускать на чистой Ubuntu 22.04/24.04 от имени root:
#
#   sudo ./install.sh
#
# Пароли и настройки спрашивает через текстовый мастер в рамках (whiptail) —
# на каждый вопрос можно нажать OK не вводя ничего, тогда подставится надёжный
# случайно сгенерированный пароль. Мастер запускается в самом начале, сразу
# после установки пакетов — дальше 10-15 минут установки K3s/KubeVirt идут
# без вопросов, можно уходить. Если whiptail недоступен (нет терминала,
# например при запуске из cron), скрипт сам переключается на обычные текстовые
# вопросы, а с флагом --yes (или -y) не спрашивает вообще ничего — все пароли
# генерируются автоматически, подходит для автоматизированного разворачивания.
#
# Скрипт делает всё за один прогон: ставит K3s, Multus, KubeVirt, CDI,
# сетевой мост br-vms, Prometheus, LVM-хранилище, создаёт .env, регистрирует
# автозапуск и поднимает панель через docker compose.
# Безопасно запускать повторно — уже выполненные шаги пропускаются.

set -e

# ============================== Вывод и утилиты ==============================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
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
step() {
    echo -e "\n${CYAN}=== $1 ===${NC}"
}

AUTO_YES=false
for arg in "$@"; do
    case "$arg" in
        -y|--yes) AUTO_YES=true ;;
    esac
done

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ "$EUID" -ne 0 ]; then
    error "Этот скрипт должен быть запущен с правами root: sudo ./install.sh"
fi

echo -e "${CYAN}"
echo "=========================================================="
echo "  ByteBurners Hosting — установка"
echo "=========================================================="
echo -e "${NC}"

# ============================== 1. Виртуализация ==============================

step "Проверка аппаратной виртуализации (KVM)"
KVM_SUPPORTED=true
if [ ! -e /dev/kvm ]; then
    warn "Устройство /dev/kvm не найдено! Аппаратная виртуализация выключена."
    warn "Если это виртуальная машина (VMware/Hyper-V/VirtualBox), включите в её"
    warn "настройках 'Virtualize Intel VT-x/EPT or AMD-V/RVI' и перезапустите скрипт."
    warn "Сейчас продолжаем в режиме программной эмуляции (будет заметно медленнее)."
    KVM_SUPPORTED=false
else
    log "Аппаратная виртуализация KVM поддерживается и доступна."
    chmod 666 /dev/kvm
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' > /etc/udev/rules.d/99-kvm.rules
    udevadm control --reload-rules && udevadm trigger || true
fi

# Вложенная виртуализация — нужна, чтобы внутри гостевых ВМ панели работал
# /dev/kvm (например, для Proxmox VE, который сам запускает виртуалки).
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
        echo Y > "/sys/module/${NESTED_MOD}/parameters/nested" 2>/dev/null || \
            modprobe -r "$NESTED_MOD" 2>/dev/null && modprobe "$NESTED_MOD" nested=1 2>/dev/null || true
        NESTED_STATE=$(cat "/sys/module/${NESTED_MOD}/parameters/nested" 2>/dev/null || echo "?")
        if [ "$NESTED_STATE" = "Y" ] || [ "$NESTED_STATE" = "1" ]; then
            log "Вложенная виртуализация включена (${NESTED_MOD})."
        else
            warn "Модуль ${NESTED_MOD} занят, вложенность применится только после: sudo reboot"
        fi
    fi
fi

step "Определение активного сетевого интерфейса"
ACTIVE_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$ACTIVE_IFACE" ]; then
    error "Не удалось определить активный сетевой интерфейс (нет маршрута по умолчанию)."
fi
log "Активный сетевой интерфейс хоста: $ACTIVE_IFACE"

# ============================== 2. Пакеты и Docker ==============================

step "Установка системных пакетов"
apt-get update
apt-get install -y curl iptables bridge-utils jq net-tools openssl nginx fail2ban whiptail

# Nginx нужен только как балансировщик (aegis_balancer_*.conf). Его дефолтный
# сайт занимает порт 80, а он нужен Caddy для HTTP-01 проверки доменов.
if [ -e /etc/nginx/sites-enabled/default ]; then
    log "Отключение дефолтного сайта nginx (порт 80 нужен Caddy для TLS)..."
    rm -f /etc/nginx/sites-enabled/default
    nginx -t &>/dev/null && systemctl reload nginx || true
fi

log "Проверка и установка Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
    apt-get install -y docker.io docker-compose-v2
    systemctl enable --now docker
    log "Docker установлен."
else
    log "Docker уже установлен."
fi

log "Проверка и установка MinIO Client (mc)..."
if ! command -v mc &> /dev/null; then
    ARCH=$(uname -m)
    [ "$ARCH" = "x86_64" ] && ARCH="amd64"
    [ "$ARCH" = "aarch64" ] && ARCH="arm64"
    curl -sSL "https://dl.min.io/client/mc/release/linux-${ARCH}/mc" -o /usr/local/bin/mc
    chmod +x /usr/local/bin/mc
    log "MinIO Client установлен."
else
    log "MinIO Client уже установлен."
fi

# ============================== Пароли (.env) ==============================
#
# Спрашиваем пароли ЗДЕСЬ, сразу после установки whiptail, а не в конце
# скрипта — дальше идёт 10-15 минут неинтерактивной установки K3s/KubeVirt,
# и раньше пользователю приходилось всё это время сидеть и ждать вопросов,
# вместо того чтобы сразу всё ответить и уйти.
#
# whiptail рисует диалог поверх терминала (как в raspi-config/Debian
# installer): результат читаем через классический трюк с обменом
# дескрипторов `3>&1 1>&2 2>&3` — whiptail пишет введённое значение в
# stderr, а рисует поверх текущего stderr, так что после обмена $(...)
# (который перехватывает только stdout) получает ровно введённый текст.
# USE_WHIPTAIL вычисляется ОДИН раз здесь, на верхнем уровне скрипта, где
# stdout/stdin ещё точно указывают на настоящий терминал — если проверять
# то же самое внутри функций, вызываемых как `x=$(ask_secret ...)`, stdout
# внутри такого вызова уже будет перенаправлен в канал захвата, а не в tty.

WT_TITLE="ByteBurners Hosting — установка"
USE_WHIPTAIL=false
if [ "$AUTO_YES" != true ] && [ -t 0 ] && [ -t 1 ] && command -v whiptail &>/dev/null; then
    USE_WHIPTAIL=true
fi

if [ "$USE_WHIPTAIL" = true ]; then
    whiptail --title "$WT_TITLE" --msgbox \
"Сейчас потребуется задать несколько паролей.\n\nДля любого поля можно просто нажать OK не вводя ничего — тогда будет использовано надёжное случайно сгенерированное значение. Дальше установка пойдёт без вопросов." \
        13 70
fi

ask_secret() {
    local prompt="$1"
    local generated
    generated=$(openssl rand -hex 24)
    if [ "$AUTO_YES" = true ]; then
        echo "$generated"
        return
    fi
    local input
    if [ "$USE_WHIPTAIL" = true ]; then
        input=$(whiptail --title "$WT_TITLE" --passwordbox \
            "${prompt}\n\nПусто + OK — использовать случайный сгенерированный пароль." \
            12 70 3>&1 1>&2 2>&3) || input=""
    else
        read -rp "${prompt} [Enter — сгенерировать случайный]: " input
    fi
    echo "${input:-$generated}"
}

ask_value() {
    local prompt="$1" default="$2"
    if [ "$AUTO_YES" = true ]; then
        echo "$default"
        return
    fi
    local input
    if [ "$USE_WHIPTAIL" = true ]; then
        input=$(whiptail --title "$WT_TITLE" --inputbox "$prompt" 11 70 "$default" 3>&1 1>&2 2>&3) || input="$default"
    else
        read -rp "${prompt} [$default]: " input
    fi
    echo "${input:-$default}"
}

detect_host_ip() {
    ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -n1
}

generate_env_file() {
    local env_file="${PROJECT_DIR}/.env"

    if [ -f "$env_file" ]; then
        log "Файл .env уже существует."
        if [ "$AUTO_YES" = true ]; then
            log "Режим --yes: использую существующий .env без изменений."
            return
        fi
        if [ "$USE_WHIPTAIL" = true ]; then
            if whiptail --title "$WT_TITLE" --yesno \
                "Найден существующий .env.\n\nОставить его без изменений и не спрашивать пароли заново?" \
                10 70; then
                log "Использую существующий .env."
                return
            fi
        else
            local keep
            read -rp "Оставить его как есть, не спрашивая пароли заново? [Y/n]: " keep
            case "$keep" in
                [nN]*) ;;
                *) log "Использую существующий .env."; return ;;
            esac
        fi
    fi

    if [ "$USE_WHIPTAIL" != true ]; then
        echo
        echo -e "${CYAN}=========================================================="
        echo " Настройка паролей (.env)"
        echo " Для каждого пункта можно просто нажать Enter — тогда будет"
        echo " использовано надёжное случайно сгенерированное значение."
        echo -e "==========================================================${NC}"
        echo
    fi

    local postgres_password admin_token aegis_secret_key rabbitmq_user rabbitmq_pass \
          minio_user minio_password mariadb_password storage_class detected_ip host_ip \
          acme_email registry_port

    postgres_password=$(ask_secret "Пароль системной базы данных PostgreSQL")
    admin_token=$(ask_secret "Токен администратора API (это же будет пароль входа в панель под admin)")
    aegis_secret_key=$(ask_secret "Ключ шифрования секретов (AEGIS_SECRET_KEY). ВАЖНО: менять после первого запуска НЕЛЬЗЯ — старые секреты перестанут расшифровываться.")
    rabbitmq_user=$(ask_value "Логин очереди RabbitMQ" "aegis")
    rabbitmq_pass=$(ask_secret "Пароль очереди RabbitMQ")
    minio_user=$(ask_value "Логин объектного хранилища MinIO" "minioadmin")
    minio_password=$(ask_secret "Пароль объектного хранилища MinIO")
    mariadb_password=$(ask_secret "Пароль root служебной MariaDB")
    storage_class=$(ask_value "Класс хранения Kubernetes (nfs-storage — только для отказоустойчивого кластера)" "local-path")
    registry_port=$(ask_value "Порт приватного реестра образов" "5000")

    detected_ip=$(detect_host_ip)
    host_ip=$(ask_value "Определён адрес сервера: ${detected_ip:-не удалось определить}. Если сервер за NAT и внешний ('белый') IP отличается — введите его, иначе оставьте пустым" "")

    acme_email=$(ask_value "E-mail для уведомлений Let's Encrypt о своих доменах (можно оставить пустым и задать позже)" "")

    {
        echo "# Сгенерировано install.sh $(date +'%Y-%m-%d %H:%M:%S')"
        echo
        echo "POSTGRES_DB=aegis"
        echo "POSTGRES_USER=postgres"
        echo "POSTGRES_PASSWORD=${postgres_password}"
        echo
        echo "ADMIN_TOKEN=${admin_token}"
        echo "AEGIS_SECRET_KEY=${aegis_secret_key}"
        echo
        echo "DATABASE_URL=postgresql+asyncpg://postgres:${postgres_password}@127.0.0.1:5432/aegis"
        echo "DB_CONN_STR=postgresql://postgres:${postgres_password}@127.0.0.1:5432/aegis?sslmode=disable"
        echo
        echo "RABBITMQ_USER=${rabbitmq_user}"
        echo "RABBITMQ_PASS=${rabbitmq_pass}"
        echo "RABBITMQ_URL=amqp://${rabbitmq_user}:${rabbitmq_pass}@localhost:5672/"
        echo
        echo "MINIO_ROOT_USER=${minio_user}"
        echo "MINIO_ROOT_PASSWORD=${minio_password}"
        echo
        echo "MARIADB_ROOT_PASSWORD=${mariadb_password}"
        echo
        echo "STORAGE_CLASS=${storage_class}"
        echo "REGISTRY_PORT=${registry_port}"
        if [ -n "$host_ip" ]; then
            echo "AEGIS_HOST_IP=${host_ip}"
        else
            echo "# AEGIS_HOST_IP=  — не задан, определяется автоматически"
        fi
        if [ -n "$acme_email" ]; then
            echo "ACME_EMAIL=${acme_email}"
        else
            echo "# ACME_EMAIL=  — не задан, уведомления Let's Encrypt отключены"
        fi
    } > "$env_file"

    chmod 600 "$env_file"
    log ".env создан (права 600)."
}

step "Настройка паролей и переменных окружения"
generate_env_file
if [ "$USE_WHIPTAIL" = true ]; then
    whiptail --title "$WT_TITLE" --msgbox \
"Готово! Дальше установка пойдёт без вопросов — K3s, KubeVirt, сеть и панель управления. Это займёт 10-15 минут, прогресс будет виден в терминале." \
        11 70
fi

# ============================== 3. K3s ==============================

step "Установка K3s (Kubernetes)"
if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -
    log "K3s установлен."
else
    log "K3s уже установлен."
fi

log "Настройка доступа к Kubernetes API (kubeconfig)..."
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
    fi
fi

log "Ожидание готовности ноды Kubernetes..."
until kubectl get nodes 2>/dev/null | grep -q "Ready"; do
    sleep 3
done
log "Kubernetes нода готова."

# ============================== 4. Multus CNI ==============================

step "Установка Multus CNI"
CNI_CONF_DIR="/var/lib/rancher/k3s/agent/etc/cni/net.d"
CNI_BIN_DIR="/var/lib/rancher/k3s/data/cni"
[ -d "$CNI_BIN_DIR" ] || CNI_BIN_DIR="/var/lib/rancher/k3s/data/current/bin"

log "Установка недостающих CNI-плагинов..."
CNI_VERSION="v1.5.1"
ARCH=$(uname -m)
[ "$ARCH" = "x86_64" ] && ARCH="amd64"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"

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

if ! curl -sSfL "$MULTUS_URL" > /tmp/multus-raw.yml; then
    warn "Не удалось скачать манифест с master, пробую стабильную версию v4.0.2..."
    curl -sSfL "$MULTUS_FALLBACK_URL" > /tmp/multus-raw.yml || error "Не удалось загрузить манифест Multus CNI. Проверьте сеть."
fi

cat /tmp/multus-raw.yml | \
sed "s|/etc/cni/net.d|${CNI_CONF_DIR}|g" | \
sed "s|/opt/cni/bin|${CNI_BIN_DIR}|g" | \
sed "s|mountPath: ${CNI_CONF_DIR}/multus.d|mountPath: /etc/cni/net.d/multus.d|g" | \
sed "s|\"socketDir\": \"/host/run/multus/\"|\"socketDir\": \"/host/run/multus/\", \"binDir\": \"${CNI_BIN_DIR}\"|g" | \
sed "s|path: ${CNI_BIN_DIR}|path: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: ${CNI_BIN_DIR}|mountPath: /var/lib/rancher/k3s/data|g" | \
sed "s|mountPath: /host${CNI_BIN_DIR}|mountPath: /host/var/lib/rancher/k3s/data|g" > /tmp/multus-k3s.yml

[ -s /tmp/multus-k3s.yml ] || error "Созданный манифест Multus CNI пуст. Сбой патчинга."
kubectl apply -f /tmp/multus-k3s.yml
rm -f /tmp/multus-raw.yml /tmp/multus-k3s.yml

kubectl patch daemonset kube-multus-ds -n kube-system --type='strategic' \
    -p='{"spec":{"template":{"spec":{"containers":[{"name":"kube-multus","resources":{"limits":{"memory":"500Mi"},"requests":{"memory":"100Mi"}}}]}}}}' || true

log "Ожидание запуска Multus CNI..."
kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s

# ============================== 5. Мост br-vms ==============================

step "Настройка сети ВМ (мост br-vms, 172.20.0.0/24)"
log "Ожидание готовности CRD NetworkAttachmentDefinition..."
for i in {1..30}; do
    kubectl get crd network-attachment-definitions.k8s.cni.cncf.io &>/dev/null && break
    sleep 5
done

# Три отдельные проверки, а не один общий "если моста нет — создать всё":
# Multus сам создаёт линк с этим именем при первом ADD для NetworkAttachmentDefinition
# типа bridge (IPAM у неё пустой, CNI адрес не назначает). Если это происходит
# раньше — единая проверка "линк уже есть" находила бы мост БЕЗ адреса и
# пропускала бы и адрес, и up. Каждый повторный запуск install.sh чинит это
# независимо от того, кто и когда создал мост.
ip link show br-vms &>/dev/null || ip link add br-vms type bridge
ip addr show dev br-vms | grep -q "172.20.0.1/24" || ip addr add 172.20.0.1/24 dev br-vms
ip link set br-vms up

sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-ip-forward.conf

log "Настройка sysctl для стабильности HDD (защита от зависаний I/O)..."
sysctl -w vm.dirty_background_ratio=5
sysctl -w vm.dirty_ratio=10
cat <<EOF > /etc/sysctl.d/99-aegis-hdd-tuning.conf
vm.dirty_background_ratio=5
vm.dirty_ratio=10
EOF

iptables -t nat -C POSTROUTING -s 172.20.0.0/24 -o "${ACTIVE_IFACE}" -j MASQUERADE &>/dev/null || \
    iptables -t nat -A POSTROUTING -s 172.20.0.0/24 -o "${ACTIVE_IFACE}" -j MASQUERADE
iptables -C FORWARD -i br-vms -j ACCEPT &>/dev/null || \
    iptables -A FORWARD -i br-vms -j ACCEPT
iptables -C FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT &>/dev/null || \
    iptables -A FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT

if dpkg -l | grep -q iptables-persistent; then
    netfilter-persistent save
else
    log "Установка iptables-persistent..."
    echo iptables-persistent iptables-persistent/italy select false | debconf-set-selections
    echo iptables-persistent iptables-persistent/sec select false | debconf-set-selections
    DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
    netfilter-persistent save
fi

log "Установка и настройка DHCP (dnsmasq) на br-vms..."
apt-get install -y dnsmasq
# Диапазон DHCP намеренно НЕ пересекается со статическим пулом ВМ
# (172.20.0.30-229, см. compute_static_ip в backend/app/api/vms.py) — иначе
# устройство, попросившее адрес по DHCP, могло бы получить тот же IP, что уже
# статически прописан в cloud-init другой ВМ.
cat <<EOF > /etc/dnsmasq.d/aegis-dhcp.conf
interface=br-vms
bind-interfaces
dhcp-range=172.20.0.231,172.20.0.250,12h
dhcp-option=option:router,172.20.0.1
dhcp-option=option:dns-server,8.8.8.8,1.1.1.1
EOF
systemctl enable dnsmasq
systemctl restart dnsmasq

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
log "Сеть ВМ настроена (статические IP через cloud-init на мосту br-vms)."

# ============================== 6. Снапшоты, KubeVirt, CDI ==============================

step "Установка KubeVirt, CDI и снапшотов"
log "Установка VolumeSnapshot CRDs..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshotclasses.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshotcontents.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/client/config/crd/snapshot.storage.k8s.io_volumesnapshots.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml || true
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v6.3.3/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml || true

log "Получение актуальной версии KubeVirt..."
KUBEVIRT_VERSION=$(curl -s https://api.github.com/repos/kubevirt/kubevirt/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
[ -z "$KUBEVIRT_VERSION" ] && KUBEVIRT_VERSION="v1.2.0"
log "Установка KubeVirt ${KUBEVIRT_VERSION}..."
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"

if [ "$KVM_SUPPORTED" = false ]; then
    kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true,"featureGates":["HotplugVolumes","DeclarativeHotplugVolumes","WorkloadSnapshots","Snapshot"]}}}}'
else
    kubectl patch kubevirt kubevirt -n kubevirt --type=merge -p '{"spec":{"configuration":{"developerConfiguration":{"featureGates":["HotplugVolumes","DeclarativeHotplugVolumes","WorkloadSnapshots","Snapshot"]}}}}'
fi

log "Ожидание запуска KubeVirt (может занять пару минут)..."
kubectl rollout status deployment/virt-operator -n kubevirt --timeout=180s
for i in {1..30}; do
    STATUS=$(kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.status.phase}' 2>/dev/null || echo "Waiting")
    if [ "$STATUS" = "Deployed" ]; then
        log "KubeVirt развёрнут."
        if [ "$KVM_SUPPORTED" = false ]; then
            kubectl patch kubevirt kubevirt -n kubevirt --type merge -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}' || true
        fi
        break
    fi
    log "Статус KubeVirt: $STATUS..."
    sleep 10
done

log "Получение актуальной версии CDI..."
CDI_VERSION=$(curl -s https://api.github.com/repos/kubevirt/containerized-data-importer/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
[ -z "$CDI_VERSION" ] && CDI_VERSION="v1.59.0"
log "Установка CDI ${CDI_VERSION}..."
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"
kubectl apply -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"

log "Ожидание готовности CDI..."
kubectl rollout status deployment/cdi-operator -n cdi --timeout=120s
for i in {1..30}; do
    STATUS=$(kubectl get cdi cdi -n cdi -o jsonpath='{.status.phase}' 2>/dev/null || echo "Waiting")
    if [ "$STATUS" = "Deployed" ]; then
        log "CDI развёрнут."
        kubectl patch cdi cdi --type=merge --patch '{"spec": {"config": {"scratchSpaceStorageClass": "local-path"}}}' || true
        kubectl patch storageprofile local-path --type=merge -p '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}' || true
        kubectl patch storageclass local-path -p '{"allowVolumeExpansion": true}' || true
        break
    fi
    log "Статус CDI: $STATUS..."
    sleep 10
done

log "Установка virtctl..."
ARCH=$(uname -m)
[ "$ARCH" = "x86_64" ] && ARCH="amd64"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"
curl -LO "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/virtctl-${KUBEVIRT_VERSION}-linux-${ARCH}"
chmod +x virtctl-${KUBEVIRT_VERSION}-linux-${ARCH}
mv virtctl-${KUBEVIRT_VERSION}-linux-${ARCH} /usr/local/bin/virtctl

# ============================== 7. Helm + Prometheus ==============================

step "Установка Helm и Prometheus (сбор метрик ВМ)"
if ! command -v helm &> /dev/null; then
    curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
    chmod +x /tmp/get_helm.sh
    /tmp/get_helm.sh
    rm -f /tmp/get_helm.sh
    log "Helm установлен."
else
    log "Helm уже установлен."
fi

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo update
kubectl create namespace prometheus || true
helm install prometheus prometheus-community/kube-prometheus-stack -n prometheus \
  --set grafana.enabled=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false || true
log "Prometheus развёрнут в namespace prometheus."

# ============================== 8. LVM-хранилище ==============================

step "Настройка блочного хранилища LVM (горячая замена дисков)"
if [ -f "${PROJECT_DIR}/scripts/install-openebs-lvm.sh" ]; then
    bash "${PROJECT_DIR}/scripts/install-openebs-lvm.sh" || warn "Настройка LVM завершилась с предупреждением — можно перезапустить позже: sudo bash scripts/install-openebs-lvm.sh"
fi

# ============================== 9. Fail2Ban ==============================

step "Настройка Fail2Ban"
JAIL_LOCAL="/etc/fail2ban/jail.local"
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
log "Fail2Ban настроен и запущен."

# ============================== 11. Автозапуск ==============================

step "Регистрация автозапуска (systemd)"

cat <<'EOF' > /usr/local/bin/aegis-network-setup.sh
#!/usr/bin/env bash
set -e
ip link show br-vms &>/dev/null || ip link add br-vms type bridge
ip addr show dev br-vms | grep -q "172.20.0.1/24" || ip addr add 172.20.0.1/24 dev br-vms
ip link set br-vms up

/sbin/sysctl -w net.ipv4.ip_forward=1

ACTIVE_IFACE=$(/sbin/ip route | grep default | awk '{print $5}' | head -n1)
if [ -n "$ACTIVE_IFACE" ]; then
    /sbin/iptables -t nat -C POSTROUTING -s 172.20.0.0/24 -o "$ACTIVE_IFACE" -j MASQUERADE &>/dev/null || \
        /sbin/iptables -t nat -A POSTROUTING -s 172.20.0.0/24 -o "$ACTIVE_IFACE" -j MASQUERADE
    /sbin/iptables -C FORWARD -i br-vms -j ACCEPT &>/dev/null || \
        /sbin/iptables -A FORWARD -i br-vms -j ACCEPT
    /sbin/iptables -C FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT &>/dev/null || \
        /sbin/iptables -A FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT
fi
EOF
chmod +x /usr/local/bin/aegis-network-setup.sh

cat <<EOF > /etc/systemd/system/aegis-network.service
[Unit]
Description=Aegis VM Network Bridge Setup
Before=k3s.service docker.service dnsmasq.service
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/aegis-network-setup.sh

[Install]
WantedBy=multi-user.target
EOF

# Requires только на docker: без него docker compose действительно не выполнить.
# k3s и мост — Wants: панель обязана подниматься, даже если кластер сломан, —
# именно через неё смотрят логи и разбираются, почему он сломан. С Requires=
# любой сбой k3s тихо оставлял сервер вообще без веб-интерфейса.
#
# ExecStop намеренно нет. Раньше здесь был `docker compose down`: systemd
# выполнял его при каждом выключении, УДАЛЯЯ контейнеры. У всех сервисов в
# docker-compose.yml стоит restart: unless-stopped — Docker сам поднимает при
# старте демона те контейнеры, что работали на момент остановки, но удалённые
# восстанавливать нечему. То есть ExecStop своими руками убирал независимый
# путь восстановления, и запуск после перезагрузки держался ровно на одном
# этом юните: не сработал он — панели нет. Без ExecStop путей два.
# Остановить панель вручную: docker compose down в каталоге проекта.
cat <<EOF > /etc/systemd/system/aegis-hosting.service
[Unit]
Description=Aegis Cloud Engine hosting control panel
Requires=docker.service
Wants=k3s.service aegis-network.service
After=docker.service k3s.service aegis-network.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecReload=/usr/bin/docker compose restart

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aegis-network.service
systemctl enable aegis-hosting.service
systemctl restart aegis-network.service
log "Автозапуск настроен: мост поднимется и панель запустится сама после перезагрузки."

# ============================== 12. Запуск панели ==============================

step "Сборка и запуск панели управления"
chmod 600 "${PROJECT_DIR}/.env" 2>/dev/null || true
docker compose up -d --build
log "Панель запущена."

# aegis-hosting.service выше был только enable'нут, а не запущен — контейнеры
# подняла прямая команда выше (с --build, чего oneshot-юнит не делает). Без
# этого systemctl status показал бы "inactive", хотя панель на самом деле
# работает: Type=oneshot с RemainAfterExit=yes требует явного `start`, чтобы
# systemd отметил юнит активным. Повторный `docker compose up -d` (уже без
# --build) идемпотентен и ничего не меняет — просто синхронизирует состояние.
systemctl start aegis-hosting.service || warn "Не удалось синхронизировать состояние aegis-hosting.service — панель работает, но 'systemctl status' может показывать неактивной до следующего docker compose up."

# ============================== Готово ==============================

source "${PROJECT_DIR}/.env" 2>/dev/null || true
FINAL_IP=$(detect_host_ip)

# Проверяем автозапуск фактически, а не считаем настроенным по факту вызова
# `systemctl enable` — если что-то из этого не прошло (например, юнит с
# ошибкой в синтаксисе), лучше сказать об этом сразу, а не после перезагрузки.
AUTOSTART_OK=true
for svc in aegis-network.service aegis-hosting.service; do
    if ! systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        warn "$svc не в автозапуске (systemctl is-enabled провалился)."
        AUTOSTART_OK=false
    fi
    if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
        warn "$svc сейчас не активен (systemctl is-active провалился)."
        AUTOSTART_OK=false
    fi
done
if ! systemctl is-enabled --quiet docker 2>/dev/null; then
    warn "docker.service не в автозапуске — панель не поднимется после перезагрузки."
    AUTOSTART_OK=false
fi
if ! systemctl is-enabled --quiet k3s 2>/dev/null; then
    warn "k3s.service не в автозапуске — панель не поднимется после перезагрузки."
    AUTOSTART_OK=false
fi

echo
echo -e "${GREEN}=========================================================="
echo " Установка завершена!"
echo -e "==========================================================${NC}"
echo " Панель управления:  http://${FINAL_IP:-<IP_сервера>}:8080"
echo " Логин:               admin"
echo " Пароль:               ${ADMIN_TOKEN:-<см. .env, поле ADMIN_TOKEN>}"
echo
if [ "$AUTOSTART_OK" = true ]; then
    echo -e " ${GREEN}Автозапуск проверен: br-vms, k3s, docker и панель поднимутся сами после reboot.${NC}"
else
    echo -e " ${YELLOW}Автозапуск настроен не полностью — см. предупреждения выше. Панель сейчас работает,"
    echo -e " но после перезагрузки может не подняться сама. Проверьте: systemctl status aegis-network aegis-hosting${NC}"
fi
echo
echo " Проверить поды кластера:      kubectl get pods -A"
echo " Проверить контейнеры панели:  docker compose ps"
echo " Логи бэкенда:                 docker compose logs -f backend"
echo " Статус автозапуска:           systemctl status aegis-network.service aegis-hosting.service"
echo
echo -e "${YELLOW} Важно: AEGIS_SECRET_KEY в .env менять после первого запуска нельзя —"
echo -e " старые секреты (пароли внешних серверов, БД, ключи S3) перестанут расшифровываться.${NC}"
echo -e "${GREEN}==========================================================${NC}"
