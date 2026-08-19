#!/usr/bin/env bash

# Скрипт установки OpenEBS LVM LocalPV и настройки блочного хранилища для горячей замены дисков (Hotplug)
# Должен запускаться на хост-сервере от имени root (sudo)

set -Eeuo pipefail

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

# Thin LVM нужен не только для экономии места. OpenEBS
# поддерживает restore из LVM snapshot только для thin-томов.
# Без dm_thin_pool класс создастся, но первый же PVC зависнет.
log "Загрузка модулей LVM snapshot/thin-pool..."
modprobe dm_snapshot || error "Не удалось загрузить dm_snapshot."
modprobe dm_thin_pool || error "Не удалось загрузить dm_thin_pool."
cat <<EOF > /etc/modules-load.d/aegis-lvm.conf
dm_snapshot
dm_thin_pool
EOF

# Если thin-pool заполнится до 100%, LVM начинает отклонять записи. Одного
# thinProvision недостаточно: dmeventd должен следить за пулом, а LVM —
# расширять его заранее, пока в VG ещё есть свободные экстенты.
#
# Не меняем глобальный /etc/lvm/lvm.conf: на сервере могут быть чужие thin-pool,
# которым нельзя без спроса менять политику расходования свободных экстентов.
# Metadata profile прикрепляется только к thin-pool'ам vg-aegis и удаляется
# вместе с Aegis по инструкции docs/LVM_RESET.md.
LVM_CONF=/etc/lvm/lvm.conf
LVM_PROFILE_DIR=/etc/lvm/profile
LVM_PROFILE_NAME=aegis-thinpool
LVM_PROFILE="${LVM_PROFILE_DIR}/${LVM_PROFILE_NAME}.profile"
if [ ! -f "$LVM_CONF" ]; then
    error "$LVM_CONF не найден. Установите пакет lvm2 и повторите запуск."
fi
command -v thin_check >/dev/null 2>&1 || \
    error "thin_check не найден. Установите пакет thin-provisioning-tools и повторите запуск."
install -d -o root -g root -m 0755 "$LVM_PROFILE_DIR"
cat <<'EOF' > "$LVM_PROFILE"
activation {
    thin_pool_autoextend_threshold = 75
    thin_pool_autoextend_percent = 20
}
EOF
chmod 0644 "$LVM_PROFILE"

# Первый thin-pool OpenEBS создаёт только при создании первого PVC, поэтому
# включить monitoring один раз прямо сейчас недостаточно. Небольшой timer
# подхватывает как уже существующие, так и появившиеся позже thin-pool'ы.
cat <<'EOF' > /usr/local/sbin/aegis-monitor-thin-pools
#!/usr/bin/env bash
set -eu
lvs --noheadings -o lv_path,segtype vg-aegis 2>/dev/null \
  | while read -r lv_path segtype; do
      if [ "$segtype" = "thin-pool" ] && [ -n "$lv_path" ]; then
          lvchange --metadataprofile aegis-thinpool --monitor y "$lv_path" >/dev/null
      fi
    done
EOF
chmod 0755 /usr/local/sbin/aegis-monitor-thin-pools
cat <<'EOF' > /etc/systemd/system/aegis-lvm-thin-monitor.service
[Unit]
Description=Enable monitoring for Aegis LVM thin pools
After=aegis-lvm-loop.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/aegis-monitor-thin-pools
EOF
cat <<'EOF' > /etc/systemd/system/aegis-lvm-thin-monitor.timer
[Unit]
Description=Periodically monitor Aegis LVM thin pools

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
Persistent=true
Unit=aegis-lvm-thin-monitor.service

[Install]
WantedBy=timers.target
EOF

# 1. Файл, loop и VG, принадлежащие только Aegis.
IMAGE=/var/lib/aegis/lvm-storage.img
VG=vg-aegis
INIT_MARKER=/var/lib/aegis/.lvm-storage.initializing
POOL_GB="${AEGIS_LVM_POOL_GB:-40}"
install -d -o root -g root -m 0700 /var/lib/aegis

# Unit пересоздаётся при каждом upgrade. ExecStop не отсоединит loop, если
# деактивация VG не удалась из-за всё ещё открытого тома.
log "Настройка службы автоподключения loop-устройства с Direct I/O..."
cat <<'EOF' > /etc/systemd/system/aegis-lvm-loop.service
[Unit]
Description=Setup loop device for Aegis LVM Storage
Before=lvm2-monitor.service k3s.service docker.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "(losetup -j /var/lib/aegis/lvm-storage.img | grep -q . || losetup -fP --direct-io=on /var/lib/aegis/lvm-storage.img) && udevadm settle && (vgchange -ay vg-aegis || true)"
ExecStop=/bin/bash -c 'if vgs vg-aegis >/dev/null 2>&1; then vgchange -an vg-aegis || exit 1; fi; LOOP_DEV=$$(losetup -j /var/lib/aegis/lvm-storage.img | cut -d: -f1 | head -n1); if [ -n "$$LOOP_DEV" ]; then losetup -d "$$LOOP_DEV"; fi'

[Install]
WantedBy=multi-user.target
EOF

IMAGE_CREATED=false
if [ -L "$IMAGE" ]; then
    error "$IMAGE является символической ссылкой — не следую по ней с правами root."
elif [ -e "$IMAGE" ]; then
    [ -f "$IMAGE" ] || error "$IMAGE существует, но не является обычным файлом."
    chmod 0600 "$IMAGE"
    log "Существующий образ $IMAGE найден; его размер не изменяется."
else
    if vgs "$VG" &>/dev/null; then
        error "$VG существует, но $IMAGE отсутствует — не использую неизвестную VG."
    fi
    case "$POOL_GB" in
        ''|*[!0-9]*) error "AEGIS_LVM_POOL_GB должен быть целым числом гигабайт, получено: '$POOL_GB'." ;;
    esac
    [ "$POOL_GB" -lt 10 ] && error "Пул меньше 10 ГБ бесполезен: на нём не поместится ни одна ВМ."
    FREE_GB=$(df -BG --output=avail /var/lib | tail -n1 | tr -dc '0-9')
    [ -n "$FREE_GB" ] || error "Не удалось определить свободное место в /var/lib."
    MAX_POOL_GB=$((FREE_GB * 80 / 100))
    [ "$POOL_GB" -le "$MAX_POOL_GB" ] || error \
        "Запрошено ${POOL_GB} ГБ, безопасный максимум — ${MAX_POOL_GB} ГБ (80% свободного места /var/lib)."
    log "Создание root-only разреженного образа на ${POOL_GB} ГБ..."
    truncate -s "${POOL_GB}G" "$IMAGE"
    chmod 0600 "$IMAGE"
    : > "$INIT_MARKER"
    chmod 0600 "$INIT_MARKER"
    IMAGE_CREATED=true
fi

systemctl daemon-reload
systemctl enable --now aegis-lvm-loop.service

LOOP_LINES=$(losetup -j "$IMAGE")
LOOP_COUNT=$(printf '%s\n' "$LOOP_LINES" | awk -F: 'NF {count++} END {print count+0}')
LOOP_DEV=$(printf '%s\n' "$LOOP_LINES" | awk -F: 'NR == 1 {print $1}')
[ "$LOOP_COUNT" -eq 1 ] && [ -n "$LOOP_DEV" ] || \
    error "Для $IMAGE ожидался ровно один loop, найдено: $LOOP_COUNT."

if vgs "$VG" &>/dev/null; then
    PV_COUNT=$(pvs --noheadings -o vg_name | awk -v vg="$VG" '$1 == vg {count++} END {print count+0}')
    PV_DEV=$(pvs --noheadings -o pv_name,vg_name | awk -v vg="$VG" '$2 == vg {print $1}')
    if [ "$PV_COUNT" -ne 1 ] || [ "$PV_DEV" != "$LOOP_DEV" ]; then
        error "$VG не принадлежит единственному loop $LOOP_DEV файла $IMAGE; остановка без изменений."
    fi
    log "Проверено: $VG использует только $LOOP_DEV файла Aegis."
else
    if [ "$IMAGE_CREATED" != true ] && [ ! -f "$INIT_MARKER" ]; then
        error "$IMAGE уже существовал, но после подключения не содержит $VG. Не выполняю pvcreate поверх возможных данных; проверьте образ вручную или выполните docs/LVM_RESET.md."
    fi
    log "Инициализация LVM на устройстве $LOOP_DEV..."
    pvcreate -y "$LOOP_DEV"
    vgcreate -y "$VG" "$LOOP_DEV"
    log "Группа томов LVM '$VG' успешно создана!"
fi
rm -f "$INIT_MARKER"

# Настройка параметров sysctl для HDD
log "Настройка параметров sysctl для стабильности HDD..."
sysctl -w vm.dirty_background_ratio=5
sysctl -w vm.dirty_ratio=10
cat <<EOF > /etc/sysctl.d/99-aegis-hdd-tuning.conf
vm.dirty_background_ratio=5
vm.dirty_ratio=10
EOF
sysctl --system

# Unit-файлы мониторинга создаются при каждом запуске скрипта, в том числе
# при обновлении уже существующей VG.
systemctl daemon-reload
systemctl enable --now aegis-lvm-thin-monitor.timer

# StorageClass immutable. Проверяем и при необходимости удаляем старый класс
# ДО Helm upgrade, чтобы несовместимый production не остался частично
# обновлённым. Любая ошибка kubectl здесь fail-closed.
SC_EXISTS=false
if SC_LOOKUP=$(kubectl get storageclass openebs-lvm -o name 2>&1); then
    SC_EXISTS=true
elif ! grep -qiE 'notfound|not found' <<<"$SC_LOOKUP"; then
    error "Не удалось проверить StorageClass openebs-lvm: $SC_LOOKUP"
fi
if [ "$SC_EXISTS" = true ]; then
    if ! CURRENT_SC=$(kubectl get storageclass openebs-lvm \
        -o jsonpath='{.provisioner}|{.volumeBindingMode}|{.parameters.volgroup}|{.parameters.thinProvision}'); then
        error "Не удалось прочитать существующий StorageClass openebs-lvm."
    fi
    EXPECTED_SC='local.csi.openebs.io|WaitForFirstConsumer|vg-aegis|yes'
    if [ "$CURRENT_SC" != "$EXPECTED_SC" ]; then
        if ! PVC_MATCHES=$(kubectl get pvc -A \
            -o jsonpath='{range .items[?(@.spec.storageClassName=="openebs-lvm")]}x{end}'); then
            error "Не удалось проверить PVC перед пересозданием StorageClass."
        fi
        if ! PV_MATCHES=$(kubectl get pv \
            -o jsonpath='{range .items[?(@.spec.storageClassName=="openebs-lvm")]}x{end}'); then
            error "Не удалось проверить PV перед пересозданием StorageClass."
        fi
        if [ -n "$PVC_MATCHES" ] || [ -n "$PV_MATCHES" ]; then
            error "Существующий openebs-lvm несовместим и содержит PVC/PV. Выполните docs/LVM_RESET.md; старые thick-тома автоматически thin не станут."
        fi
        log "Несовместимый StorageClass пуст — безопасно пересоздаю его."
        kubectl delete storageclass openebs-lvm
    fi
fi

# 2. Установка OpenEBS LVM LocalPV драйвера в Kubernetes
log "Добавление Helm-репозитория OpenEBS..."
if ! command -v helm &> /dev/null; then
    error "Helm не установлен. Запустите сначала install.sh из корня проекта."
fi

helm repo add openebs-lvm https://openebs.github.io/lvm-localpv --force-update
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
# Восстановление тома из snapshot появилось в LocalPV-LVM 1.8.0. Фиксируем
# проверенную версию: более старый чарт примет снимок, но не сможет его
# восстановить; плавающий latest меняет production без ревью.
OPEN_EBS_LVM_CHART_VERSION="${OPEN_EBS_LVM_CHART_VERSION:-1.9.0}"
helm upgrade --install openebs-lvm openebs-lvm/lvm-localpv \
  --version "$OPEN_EBS_LVM_CHART_VERSION" \
  --namespace openebs-lvm \
  --create-namespace \
  --atomic \
  --timeout 180s \
  --set crds.csi.volumeSnapshots.enabled=false

log "Ожидание готовности подов OpenEBS LVM..."
kubectl rollout status deployment --all -n openebs-lvm --timeout=180s
kubectl rollout status daemonset --all -n openebs-lvm --timeout=180s
kubectl wait --for=condition=Ready pod --all -n openebs-lvm --timeout=180s

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
  # Restore из snapshot в OpenEBS LVM работает только для thin-томов.
  # Без этого снимок может стать Ready, но откат сорвётся.
  thinProvision: "yes"
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
# Filesystem — это реальный volumeMode DataVolume-шаблонов Linux,
# Windows и ISO этой панели. Клон между Block и Filesystem CDI не делает.
log "Настройка StorageProfile для openebs-lvm..."
kubectl patch storageprofile openebs-lvm --type=merge -p \
  '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}' \
  || log "StorageProfile openebs-lvm ещё не создан CDI — панель задаёт режимы явно, это не помешает."

log "=========================================================="
log "Установка завершена! Блочное хранилище 'openebs-lvm' готово."
log "Снимки виртуальных машин также готовы к работе."
log "Новые диски будут создаваться как thin LVM-тома в режиме Filesystem."
log "=========================================================="
