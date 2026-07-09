#!/usr/bin/env bash

# Скрипт автоматической настройки Worker-ноды (node-2) для KubeVirt HA кластера
# Должен запускаться от имени root на node-2

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
    warn "Устройство /dev/kvm не найдено! Включите вложенную виртуализацию (Nested Virtualization) в Hyper-V для node-2."
    warn "Иначе ВМ на этой ноде будут запускаться в режиме медленной программной эмуляции."
else
    log "Аппаратная виртуализация KVM поддерживается и доступна."
    chmod 666 /dev/kvm
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' > /etc/udev/rules.d/99-kvm.rules
    udevadm control --reload-rules && udevadm trigger || true
fi

# 2. Установка NFS клиента
log "Установка клиента NFS (nfs-common)..."
apt-get update
apt-get install -y nfs-common curl jq

# 3. Подключение к кластеру
read -p "Введите IP-адрес Master-ноды (node-1): " MASTER_IP
if [ -z "$MASTER_IP" ]; then
    error "IP-адрес Master-ноды не может быть пустым."
fi

read -p "Введите K3S Join Token (сгенерированный на node-1): " JOIN_TOKEN
if [ -z "$JOIN_TOKEN" ]; then
    error "Токен подключения не может быть пустым."
fi

log "Установка K3s в режиме Worker (Agent)..."
if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | K3S_URL="https://${MASTER_IP}:6443" K3S_TOKEN="${JOIN_TOKEN}" sh -
    log "K3s Agent успешно запущен и присоединен к кластеру!"
else
    log "K3s уже установлен."
fi

log "Установка Worker-ноды (node-2) завершена!"
log "Через минуту проверьте статус ноды на node-1 с помощью команды: kubectl get nodes"
