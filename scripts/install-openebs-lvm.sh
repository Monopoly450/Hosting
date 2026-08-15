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

# Размер пула передаёт install.sh (там он считается от свободного места).
# 40 ГБ — запасное значение для запуска скрипта руками: из этого пула
# нарезаются ВСЕ диски ВМ, и на 40 ГБ их поместится пара штук.
POOL_GB="${AEGIS_LVM_POOL_GB:-40}"
case "$POOL_GB" in
    ''|*[!0-9]*) error "AEGIS_LVM_POOL_GB должен быть целым числом гигабайт, получено: '$POOL_GB'." ;;
esac
[ "$POOL_GB" -lt 10 ] && error "Пул меньше 10 ГБ бесполезен: на нём не поместится ни одна ВМ."

# 1. Создание виртуального диска для LVM (если группы vg-aegis еще нет)
if vgs vg-aegis &>/dev/null; then
    log "Группа томов LVM 'vg-aegis' уже существует (размер не меняется — пул создаётся один раз)."
else
    log "Создание разреженного файла-образа на ${POOL_GB} ГБ для блочного хранилища (мгновенно)..."
    mkdir -p /var/lib/aegis
    truncate -s "${POOL_GB}G" /var/lib/aegis/lvm-storage.img

    log "Создание службы автоподключения петлевого устройства (loop device) с Direct I/O..."
    cat <<EOF > /etc/systemd/system/aegis-lvm-loop.service
[Unit]
Description=Setup loop device for Aegis LVM Storage
Before=lvm2-monitor.service k3s.service docker.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "(losetup -j /var/lib/aegis/lvm-storage.img | grep -q . || losetup -fP --direct-io=on /var/lib/aegis/lvm-storage.img) && udevadm settle && (vgchange -ay vg-aegis || true)"
ExecStop=/bin/bash -c "vgchange -an vg-aegis; LOOP_DEV=\\\$(losetup -j /var/lib/aegis/lvm-storage.img | awk -F: '{print \\\$1}'); if [ -n \\\"\\\$LOOP_DEV\\\" ]; then losetup -d \\\$LOOP_DEV; fi"

[Install]
WantedBy=multi-user.target
EOF

    # Настройка параметров sysctl для HDD
    log "Настройка параметров sysctl для стабильности HDD..."
    sysctl -w vm.dirty_background_ratio=5
    sysctl -w vm.dirty_ratio=10
    cat <<EOF > /etc/sysctl.d/99-aegis-hdd-tuning.conf
vm.dirty_background_ratio=5
vm.dirty_ratio=10
EOF
    sysctl --system

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
    error "Helm не установлен. Запустите сначала install.sh из корня проекта."
fi

helm repo add openebs-lvm https://openebs.github.io/lvm-localpv || true
helm repo update

log "Установка OpenEBS LVM LocalPV драйвера..."
# crds.csi.volumeSnapshots.enabled=false — иначе установка падает так:
#
#   CustomResourceDefinition "volumesnapshotcontents.snapshot.storage.k8s.io"
#   exists and cannot be imported into the current release: invalid ownership
#   metadata; label validation error: missing key
#   "app.kubernetes.io/managed-by": must be set to "Helm"
#
# Эти CRD уже поставил install.sh обычным kubectl apply (вместе со
# snapshot-controller, без которого снимки не работают вовсе), поэтому
# метаданных владения Helm на них нет, и чарт отказывается их присваивать.
#
# Отключаем их в чарте, а не проставляем метки владения существующим CRD:
# при втором варианте CRD оказались бы в собственности релиза openebs-lvm, и
# его удаление снесло бы снимки KubeVirt заодно. Источник правды для этих CRD
# — install.sh, чарту они не нужны.
helm upgrade --install openebs-lvm openebs-lvm/lvm-localpv \
  --namespace openebs-lvm \
  --create-namespace \
  --set crds.csi.volumeSnapshots.enabled=false

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

# 4. Класс снимков томов.
#
# Без него снимки ВМ не работают, причём МОЛЧА: install.sh ставит CRD
# VolumeSnapshot и snapshot-controller и включает у KubeVirt feature gate
# Snapshot, поэтому объект VirtualMachineSnapshot создаётся успешно и
# панель показывает его как «создаётся». Но создать за ним настоящий
# VolumeSnapshot не из чего — класса нет ни одного, — и снимок навсегда
# остаётся в Pending с readyToUse=false. Снаружи это выглядит как «снимки
# не создаются».
log "Создание VolumeSnapshotClass 'openebs-lvm-snapshot'..."
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: openebs-lvm-snapshot
  annotations:
    # Класс по умолчанию: KubeVirt не указывает класс явно при снятии
    # снимка ВМ и полагается на дефолтный.
    snapshot.storage.kubernetes.io/is-default-class: "true"
driver: local.csi.openebs.io
deletionPolicy: Delete
EOF

# 5. Профиль хранилища для CDI.
#
# CDI заполняет StorageProfile сам только для классов, которые знает в лицо.
# Для openebs-lvm профиль остаётся пустым, и любой DataVolume без явных
# accessModes/volumeMode встаёт намертво:
#
#   ErrClaimNotValid: no accessMode specified in StorageProfile openebs-lvm
#
# Внешне это выглядит как «бэкап создался и вечно висит в неизвестном
# состоянии». Панель с тех пор проставляет режимы явно (см. k8s_client),
# но профиль всё равно нужен: по нему CDI решает и за нас, и за всех
# остальных, кто создаёт тома на этом классе.
#
# Block — потому что LVM отдаёт сырое блочное устройство, и диски ВМ панель
# создаёт блочными. Клон между Block и Filesystem CDI не делает.
log "Настройка StorageProfile для openebs-lvm..."
kubectl patch storageprofile openebs-lvm --type=merge -p \
  '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Block"}]}}' \
  || log "StorageProfile openebs-lvm ещё не создан CDI — панель задаёт режимы явно, это не помешает."

log "=========================================================="
log "Установка завершена! Блочное хранилище 'openebs-lvm' готово."
log "Снимки виртуальных машин также готовы к работе."
log "Теперь диски будут создаваться как сырые блочные устройства"
log "и монтироваться к виртуальным машинам «на лету»."
log "=========================================================="
