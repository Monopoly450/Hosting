# Полный сброс Aegis LVM и обновление панели

> **Необратимо:** процедура удаляет все диски ВМ, VM-бэкапы, снимки,
> сетевые PVC и приватные базы данных, использующие StorageClass
> `openebs-lvm`. Docker-тома PostgreSQL, MinIO, MariaDB и почты она не
> затрагивает. Никогда не выполняйте здесь `docker compose down -v` или
> `losetup -D`.

Инсталлятор не меняет глобальные параметры `/etc/lvm/lvm.conf`: политика
autoextend хранится в отдельном metadata profile `aegis-thinpool` и относится
только к thin-pool группы `vg-aegis`.

Старые thick-тома нельзя превратить в thin заменой StorageClass. После
сброса все ВМ и другие PVC на `openebs-lvm` нужно создать заново.

## 1. Удалить ресурсы через панель и сохранить служебные данные

Сначала в панели удалите расписания бэкапов, VM-бэкапы, снимки, виртуальные
машины, сетевые диски и приватные базы данных. Так записи PostgreSQL панели
останутся согласованными с Kubernetes.

Затем на сервере:

```bash
set -euo pipefail
cd ~/Hosting
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$HOME/aegis-pre-lvm-reset-$STAMP"
mkdir -m 700 "$BACKUP_DIR"
cp -a .env "$BACKUP_DIR/.env"
git rev-parse HEAD > "$BACKUP_DIR/git-commit.txt"
DUMP_TMP="$BACKUP_DIR/aegis.dump.tmp"
docker compose exec -T db pg_dump -U postgres -d aegis -Fc > "$DUMP_TMP"
test -s "$DUMP_TMP"
mv "$DUMP_TMP" "$BACKUP_DIR/aegis.dump"

docker compose stop frontend backend worker aegis-orchestrator
```

Если панель уже не способна удалить объекты, команды ниже удалят **все**
виртуальные машины и связанные объекты в namespace `default`. Используйте
их только если этот namespace целиком принадлежит Aegis; записи панели в
PostgreSQL после такого аварийного удаления придётся чистить отдельно.

```bash
set -euo pipefail
kubectl delete virtualmachines.kubevirt.io --all -n default --wait=true
kubectl delete virtualmachinerestores.snapshot.kubevirt.io --all -n default --wait=true
kubectl delete virtualmachinesnapshots.snapshot.kubevirt.io --all -n default --wait=true
kubectl delete datavolumes.cdi.kubevirt.io --all -n default --wait=true
kubectl delete volumesnapshots.snapshot.storage.k8s.io --all -n default --wait=true

kubectl get pvc -A \
  -o jsonpath='{range .items[?(@.spec.storageClassName=="openebs-lvm")]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' \
  | while read -r namespace pvc; do
      [ -n "$namespace" ] && kubectl delete pvc "$pvc" -n "$namespace" --wait=true
    done
```

## 2. Убедиться, что хранилище больше никто не использует

```bash
set -euo pipefail
kubectl get pvc -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,SC:.spec.storageClassName
kubectl get pv -o custom-columns=NAME:.metadata.name,SC:.spec.storageClassName,STATUS:.status.phase
kubectl get volumesnapshots.snapshot.storage.k8s.io -A
kubectl get volumesnapshotcontents.snapshot.storage.k8s.io
kubectl get lvmvolumes.local.openebs.io -A
kubectl get lvmsnapshots.local.openebs.io -A
```

Строк с `openebs-lvm` и объектов `LVMVolume`/`LVMSnapshot` быть не должно.
Если объект висит в `Terminating`, остановитесь и выясните, какой контроллер
или Pod его удерживает. Не снимайте finalizer вслепую: так можно оставить
реальный LV без владельца.

После чистой проверки удалите только компоненты Aegis LVM. Глобальные CRD
`snapshot.storage.k8s.io`, snapshot-controller, KubeVirt и CDI не удаляются.

```bash
set -euo pipefail
helm uninstall openebs-lvm -n openebs-lvm
kubectl delete storageclass openebs-lvm --ignore-not-found
kubectl delete volumesnapshotclass openebs-lvm-snapshot --ignore-not-found
kubectl delete storageprofile.cdi.kubevirt.io openebs-lvm --ignore-not-found
kubectl delete namespace openebs-lvm --ignore-not-found --wait=true
```

## 3. Удалить только принадлежащий Aegis VG и loop-образ

Сначала команда доказывает, что у `vg-aegis` ровно один PV и это именно
loop-устройство файла `/var/lib/aegis/lvm-storage.img`. При несовпадении она
останавливается — не подставляйте другой диск наугад.

```bash
set -euo pipefail
IMAGE=/var/lib/aegis/lvm-storage.img
VG=vg-aegis

LOOP_DEV=$(sudo losetup -j "$IMAGE" | awk -F: 'NR == 1 {print $1}')
LOOP_COUNT=$(sudo losetup -j "$IMAGE" | awk -F: 'NF {count++} END {print count+0}')
PV_DEV=$(sudo pvs --noheadings -o pv_name,vg_name | awk -v vg="$VG" '$2 == vg {print $1}')
PV_COUNT=$(sudo pvs --noheadings -o vg_name | awk -v vg="$VG" '$1 == vg {count++} END {print count+0}')

if [ "$LOOP_COUNT" -ne 1 ] || [ "$PV_COUNT" -ne 1 ] || [ "$PV_DEV" != "$LOOP_DEV" ]; then
  echo "СТОП: vg-aegis не совпадает с единственным loop для $IMAGE" >&2
  exit 1
fi

sudo systemctl disable --now aegis-lvm-thin-monitor.timer || true
if sudo lvs "$VG" >/dev/null 2>&1; then
  sudo lvremove -fy "$VG"
fi
sudo vgremove -fy "$VG"
sudo pvremove -fy "$LOOP_DEV"
sudo systemctl disable --now aegis-lvm-loop.service || true
if sudo losetup "$LOOP_DEV" >/dev/null 2>&1; then
  sudo losetup -d "$LOOP_DEV"
fi
if sudo losetup -j "$IMAGE" | grep -q .; then
  echo "СТОП: loop для $IMAGE всё ещё подключён; image не удалён" >&2
  exit 1
fi

sudo rm -f /var/lib/aegis/lvm-storage.img
sudo rm -f /etc/systemd/system/aegis-lvm-loop.service
sudo rm -f /etc/systemd/system/aegis-lvm-thin-monitor.service
sudo rm -f /etc/systemd/system/aegis-lvm-thin-monitor.timer
sudo rm -f /usr/local/sbin/aegis-monitor-thin-pools
sudo rm -f /etc/modules-load.d/aegis-lvm.conf
sudo rm -f /etc/lvm/profile/aegis-thinpool.profile
sudo rm -f /var/lib/aegis/.lvm-storage.initializing
sudo systemctl daemon-reload
sudo udevadm settle
```

## 4. Загрузить обновление и создать новое thin-LVM

`git status --short` должен быть пустым. Если он показывает tracked-файлы,
остановитесь и сохраните изменения — не используйте `reset --hard`.

```bash
set -euo pipefail
cd ~/Hosting
git status --short
git fetch origin
git log --oneline HEAD..origin/main
git pull --ff-only origin main
git rev-parse --short HEAD

if grep -q '^STORAGE_CLASS=' .env; then
  sed -i 's/^STORAGE_CLASS=.*/STORAGE_CLASS=openebs-lvm/' .env
else
  printf '\nSTORAGE_CLASS=openebs-lvm\n' >> .env
fi

FREE_GB=$(df -BG --output=avail /var/lib | tail -n1 | tr -dc '0-9')
POOL_GB=$((FREE_GB * 60 / 100))
if [ "$POOL_GB" -lt 10 ]; then
  echo "Недостаточно свободного места для LVM" >&2
  exit 1
fi
echo "Новый разреженный LVM-образ: ${POOL_GB} ГБ"
sudo env AEGIS_LVM_POOL_GB="$POOL_GB" bash scripts/install-openebs-lvm.sh

docker compose config --quiet
docker compose up -d --build
```

Публичный репозиторий клонируется и обновляется без GitHub PAT. Если токен
когда-либо был отправлен в чат или лог, его нужно отозвать в GitHub и создать
новый только для задач, которым действительно нужна запись.

## 5. Проверить результат

```bash
set -euo pipefail
kubectl get storageclass openebs-lvm \
  -o jsonpath='{.parameters.thinProvision}{"\n"}'
kubectl get volumesnapshotclass openebs-lvm-snapshot
kubectl get storageprofile openebs-lvm \
  -o jsonpath='{.spec.claimPropertySets}{"\n"}'
kubectl wait --for=condition=Ready pod --all -n openebs-lvm --timeout=180s
helm list -n openebs-lvm

sudo systemctl is-active aegis-lvm-loop.service
sudo systemctl is-active aegis-lvm-thin-monitor.timer
docker compose ps
curl -fsS http://127.0.0.1:8000/
docker compose logs --since=10m backend worker \
  | grep -iE 'error|traceback|failed|ErrClaimNotValid' || true
```

Первая команда должна вывести `yes`, StorageProfile — `Filesystem`, а Pod'ы
OpenEBS и контейнеры — быть готовыми. После сброса создайте новую тестовую ВМ
и проверьте один снимок, откат и бэкап. У снимка одного диска реальный прогресс
обычно меняется сразу с 0 на 100; у CDI-клона процент может быть `N/A`, поэтому
панель показывает анимированное «идёт…» до конечного статуса.
