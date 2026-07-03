#!/usr/bin/env bash

# Скрипт автоматической настройки выделенной СХД (NFS-сервера) на san-storage
# Должен запускаться от имени root на сервере СХД (san-storage)

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

# Установка необходимых пакетов
log "Установка пакетов lvm2 и nfs-kernel-server..."
apt-get update
apt-get install -y lvm2 nfs-kernel-server

# Инициализация диска под LVM (по умолчанию делаем через разреженный файл на 40ГБ, если не передан физический диск)
DISK_DEV=""
if [ -n "$1" ]; then
    DISK_DEV="$1"
    log "Используем переданное физическое устройство для LVM: $DISK_DEV"
else
    log "Физический диск не передан в аргументах. Создаем разреженный loop-файл на 40ГБ..."
    mkdir -p /var/lib/aegis
    LOOP_FILE="/var/lib/aegis/lvm-storage.img"
    if [ ! -f "$LOOP_FILE" ]; then
        truncate -s 40G "$LOOP_FILE"
        log "Файл-образ $LOOP_FILE успешно создан."
    else
        log "Файл-образ $LOOP_FILE уже существует."
    fi

    # Настраиваем loop-устройство
    LOOP_DEV=$(losetup -j "$LOOP_FILE" | awk -F: '{print $1}' | head -n1)
    if [ -z "$LOOP_DEV" ]; then
        LOOP_DEV=$(losetup -f --show "$LOOP_FILE")
        log "Подключено loop-устройство: $LOOP_DEV"
    else
        log "Loop-устройство уже подключено к: $LOOP_DEV"
    fi
    DISK_DEV="$LOOP_DEV"

    # Создаем службу автоподключения loop-файла при перезагрузке
    log "Создание службы автоподключения loop-диска aegis-lvm-loop.service..."
    tee /etc/systemd/system/aegis-lvm-loop.service > /dev/null <<EOF
[Unit]
Description=Attach Loop Device for Aegis Storage
DefaultDependencies=no
After=systemd-udev-trigger.service
Before=local-fs-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/losetup -f $LOOP_FILE
ExecStop=/bin/sh -c '/sbin/losetup -j $LOOP_FILE | cut -d: -f1 | xargs -r /sbin/losetup -d'

[Install]
WantedBy=local-fs-pre.target
EOF
    systemctl daemon-reload
    systemctl enable aegis-lvm-loop.service
fi

# Создаем LVM PV, VG и LV
log "Настройка LVM группы томов vg0..."
if ! pvdisplay "$DISK_DEV" &>/dev/null; then
    pvcreate "$DISK_DEV"
fi

if ! vgdisplay vg0 &>/dev/null; then
    vgcreate vg0 "$DISK_DEV"
fi

if ! lvdisplay /dev/vg0/shared-lv &>/dev/null; then
    # Выделяем все доступное место под общий логический том
    lvcreate -l 100%FREE -n shared-lv vg0
fi

# Создаем файловую систему
log "Создание файловой системы ext4 на /dev/vg0/shared-lv..."
if ! blkid /dev/vg0/shared-lv | grep -q "ext4"; then
    mkfs.ext4 /dev/vg0/shared-lv
fi

# Монтируем диск СХД
MOUNT_POINT="/mnt/shared-pvc"
log "Монтирование диска в $MOUNT_POINT..."
mkdir -p "$MOUNT_POINT"
if ! mount | grep -q "$MOUNT_POINT"; then
    mount /dev/vg0/shared-lv "$MOUNT_POINT"
fi

# Добавляем в /etc/fstab для авто-монтирования
if ! grep -q "$MOUNT_POINT" /etc/fstab; then
    echo "/dev/vg0/shared-lv $MOUNT_POINT ext4 defaults 0 2" >> /etc/fstab
    log "Настройка авто-монтирования в /etc/fstab завершена."
fi

# Настраиваем права на папку шары (чтобы KubeVirt/QEMU под UID 107 мог читать и писать диски)
log "Настройка прав доступа на каталог NFS..."
chmod 777 "$MOUNT_POINT"
chown nobody:nogroup "$MOUNT_POINT"

# Настройка NFS экспорта
log "Настройка NFS сервера в /etc/exports..."
# Разрешаем доступ для всей локальной подсети. Вы можете настроить более узкий IP-диапазон.
NFS_LINE="$MOUNT_POINT *(rw,sync,no_subtree_check,no_root_squash)"
if ! grep -q "$MOUNT_POINT" /etc/exports; then
    echo "$NFS_LINE" >> /etc/exports
fi

# Перезапуск службы NFS
log "Запуск и перезапуск NFS-сервера..."
systemctl daemon-reload
systemctl enable nfs-kernel-server
systemctl restart nfs-kernel-server

# Установка и запуск node-exporter для сбора метрик СХД в Prometheus
log "Установка prometheus-node-exporter для мониторинга ресурсов СХД..."
apt-get install -y prometheus-node-exporter
systemctl enable prometheus-node-exporter
systemctl restart prometheus-node-exporter

log "Настройка СХД успешно завершена!"
log "IP-адрес СХД: $(hostname -I | awk '{print $1}')"
log "Путь экспорта: $MOUNT_POINT"
log "Убедитесь, что порты NFS (111, 2049) и Node Exporter (9100) открыты в брандмауэре СХД."
