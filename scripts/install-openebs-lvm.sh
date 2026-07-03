#!/usr/bin/env bash

# Скрипт установки OpenEBS LVM LocalPV и настройки блочного хранилища для горячей замены дисков (Hotplug)
# Должен запускаться на хост-сервере от имени root (sudo)

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[INFO]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"
    exit 1
}

if [ "$EUID" -ne 0 ]; then
    error "Этот скрипт должен быть запущен с правами root (через sudo)."
fi

# 1. Создание виртуального диска для LVM (если группы vg-aegis еще нет)
if vgs vg-aegis &>/dev/null; then
    log "Группа томов LVM 'vg-aegis' уже существует."
else
    log "Создание разреженного файла-образа на 40 ГБ для блочного хранилища (мгновенно)..."
    mkdir -p /var/lib/aegis
    truncate -s 40G /var/lib/aegis/lvm-storage.img

    log "Создание службы автоподключения петлевого устройства (loop device)..."
    cat <<EOF > /etc/systemd/system/aegis-lvm-loop.service
[Unit]
Description=Setup loop device for Aegis LVM Storage
Before=lvm2-monitor.service k3s.service docker.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "(/sbin/losetup -j /var/lib/aegis/lvm-storage.img | grep -q . || /sbin/losetup -fP /var/lib/aegis/lvm-storage.img) && /sbin/udevadm settle && (/sbin/vgchange -ay vg-aegis || true)"
ExecStop=/bin/bash -c "/sbin/vgchange -an vg-aegis; LOOP_DEV=\\\$(/sbin/losetup -j /var/lib/aegis/lvm-storage.img | awk -F: '{print \\\$1}'); if [ -n \\\"\\\$LOOP_DEV\\\" ]; then /sbin/losetup -d \\\$LOOP_DEV; fi"

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now aegis-lvm-loop.service

    # Инициализация LVM
    LOOP_DEV=$(losetup -j /var/lib/aegis/lvm-storage.img | awk -F: '{print $1}' | head -n1)
    if [ -z "$LOOP_DEV" ]; then
        error "Не удалось подключить файл-образ как loop device."
    fi

    log "Инициализация LVM на устройстве $LOOP_DEV..."
    pvcreate -y "$LOOP_DEV"
    vgcreate -y vg-aegis "$LOOP_DEV"
    log "Группа томов LVM 'vg-aegis' успешно создана!"
fi

# 2. Установка OpenEBS LVM LocalPV драйвера в Kubernetes
log "Добавление Helm-репозитория OpenEBS..."
if ! command -v helm &> /dev/null; then
    error "Helm не установлен. Запустите сначала bootstrap-host.sh"
fi

helm repo add openebs-lvm https://openebs.github.io/lvm-localpv || true
helm repo update

log "Установка OpenEBS LVM LocalPV драйвера..."
helm upgrade --install openebs-lvm openebs-lvm/lvm-localpv \
  --namespace openebs-lvm \
  --create-namespace

log "Ожидание готовности подов OpenEBS LVM..."
sleep 5
DEPLOYMENT_NAME=$(kubectl get deployments -n openebs-lvm -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$DEPLOYMENT_NAME" ]; then
    kubectl rollout status "deployment/$DEPLOYMENT_NAME" -n openebs-lvm --timeout=120s
else
    log "Деплоймент в namespace openebs-lvm не обнаружен. Пропускаем ожидание..."
fi

# 3. Создание StorageClass для блочных томов
log "Создание StorageClass 'openebs-lvm'..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: openebs-lvm
provisioner: local.csi.openebs.io
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  storage: "lvm"
  volgroup: "vg-aegis"
EOF

log "=========================================================="
log "Установка завершена! Блочное хранилище 'openebs-lvm' готово."
log "Теперь диски будут создаваться как сырые блочные устройства"
log "и монтироваться к виртуальным машинам «на лету»."
log "=========================================================="
