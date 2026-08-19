import os
import sys
from datetime import datetime

# Тестовое окружение должно быть настроено до импорта модулей приложения
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.scheduled_backups import compute_next_run, _backup_timestamp

# Суббота, 18 июля 2026, 14:30 UTC (weekday()==5)
NOW = datetime(2026, 7, 18, 14, 30, 0)


def test_hourly_rolls_to_next_hour_when_minute_passed():
    # минута 15 уже прошла в текущем часу -> следующий час
    assert compute_next_run("hourly", 3, 15, None, NOW) == datetime(2026, 7, 18, 15, 15, 0)


def test_hourly_same_hour_when_minute_ahead():
    assert compute_next_run("hourly", 3, 45, None, NOW) == datetime(2026, 7, 18, 14, 45, 0)


def test_daily_next_day_when_time_passed():
    assert compute_next_run("daily", 3, 0, None, NOW) == datetime(2026, 7, 19, 3, 0, 0)


def test_daily_same_day_when_time_ahead():
    assert compute_next_run("daily", 23, 0, None, NOW) == datetime(2026, 7, 18, 23, 0, 0)


def test_weekly_advances_to_target_weekday():
    # понедельник (0) -> ближайший понедельник 20 июля
    assert compute_next_run("weekly", 3, 0, 0, NOW) == datetime(2026, 7, 20, 3, 0, 0)


def test_weekly_today_when_time_ahead():
    # суббота (5), время ещё не наступило -> сегодня
    assert compute_next_run("weekly", 23, 0, 5, NOW) == datetime(2026, 7, 18, 23, 0, 0)


def test_weekly_next_week_when_time_passed_today():
    # суббота (5), 03:00 уже прошло -> следующая суббота
    assert compute_next_run("weekly", 3, 0, 5, NOW) == datetime(2026, 7, 25, 3, 0, 0)


def test_always_strictly_in_future():
    for freq in ("hourly", "daily", "weekly"):
        assert compute_next_run(freq, NOW.hour, NOW.minute, NOW.weekday(), NOW) > NOW


def test_backup_timestamp_parsing():
    assert _backup_timestamp("web-1-backup-1752849000") == 1752849000
    assert _backup_timestamp("garbage") == 0


def test_retention_never_deletes_last_good_backup_for_pending_one():
    from app.services.scheduled_backups import prune_vm_backups

    class K8s:
        deleted = []

        def list_vm_backups(self, _name):
            return [
                {"name": "web-backup-3", "status": "CloneInProgress"},
                {"name": "web-backup-2", "status": "Succeeded"},
                {"name": "web-backup-1", "status": "Succeeded"},
            ]

        def delete_vm_backup(self, name):
            self.deleted.append(name)

    k8s = K8s()
    prune_vm_backups(k8s, "web", retention=2)
    assert k8s.deleted == []


# ---------- снимки: без класса снимков томов они не работают вовсе ----------
#
# Живой случай: снимки «не создаются». На деле объект VirtualMachineSnapshot
# создавался успешно и панель показывала «создаётся», но readyToUse не
# становился true никогда — KubeVirt нечем сделать настоящий VolumeSnapshot.
# install.sh ставит CRD и snapshot-controller и включает feature gate
# Snapshot, а VolumeSnapshotClass не создавал никто. Плюс хранилище по
# умолчанию (local-path) — вообще не CSI-драйвер и снимки не умеет.

def test_snapshot_creation_refuses_without_a_volume_snapshot_class():
    """Отказ сразу и с объяснением лучше объекта, который навсегда зависнет
    в Pending: пользователь иначе ждёт снимок, которого не будет.

    Проверка с тех пор стала строже — сверяется драйвер класса снимков с
    провизионером диска именно этой ВМ, а не «есть ли в кластере хоть один
    класс». Слабой версии хватало, чтобы пропустить снимок без диска."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "snapshots.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert "client.snapshot_support(vm_name)" in src
    # Сообщение обязано называть причину и путь решения, а не просто «ошибка».
    assert "local-path" in src and "install-openebs-lvm.sh" in src


def test_lvm_installer_creates_the_snapshot_class():
    """LVM-драйвер снимки умеет, но без класса они всё равно не заработают."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "scripts", "install-openebs-lvm.sh"), encoding="utf-8") as f:
        sh = f.read()

    assert "kind: VolumeSnapshotClass" in sh
    assert "driver: local.csi.openebs.io" in sh
    # KubeVirt не указывает класс явно — берётся дефолтный.
    assert "is-default-class" in sh


def test_backup_picks_the_exact_disk_of_the_vm():
    """Windows имеет и системный HD, и установочный ISO. Порядок PVC не
    должен превращать резервную копию системы в копию установочного диска."""
    from app.core.k8s_client import _primary_disk_pvc_name

    vm = {
        "spec": {
            "template": {"spec": {
                "domain": {"devices": {"disks": [
                    {"name": "winiso", "cdrom": {"bus": "sata"}},
                    {"name": "winhd", "disk": {"bus": "virtio"}},
                ]}},
                "volumes": [
                    {"name": "winiso", "dataVolume": {"name": "demo-iso"}},
                    {"name": "winhd", "dataVolume": {"name": "demo-hd"}},
                ],
            }},
            "dataVolumeTemplates": [
                {"metadata": {"name": "demo-hd"}},
                {"metadata": {"name": "demo-iso"}},
            ],
        }
    }
    assert _primary_disk_pvc_name(vm) == "demo-hd"


def _backup_list_jsx():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "components", "BackupList.jsx"), encoding="utf-8") as f:
        return f.read()


def test_backup_row_uses_theme_colours():
    """Строка заливалась rgba(0,0,0,0.2) — чёрным поверх фона. В тёмной теме
    это сходило за подложку, в светлой давало серую плашку, на которой не
    читались ни название копии, ни кнопки."""
    src = _backup_list_jsx()
    assert "rgba(0, 0, 0, 0.2)" not in src
    assert "var(--bg-surface-hover)" in src


def test_backup_in_progress_is_not_shown_as_an_error():
    """Разбирались три фазы DataVolume из полутора десятков, остальные падали
    в default и рисовались красным «ошибка». Копия, которая спокойно
    клонируется, выглядела сломанной."""
    src = _backup_list_jsx()
    for phase in ("CloneInProgress", "WaitForFirstConsumer", "PendingPopulation", "ImportInProgress"):
        assert phase in src, f"фаза {phase} снова попадёт в «ошибка»"


def test_restore_button_is_always_visible():
    """Кнопка рисовалась только у готовой копии. У всех остальных на строке
    оставалась одна корзина, и выглядело это как «восстановления в панели
    нет». Показываем всегда, отключаем пока копия не готова: восстановить из
    наполовину склонированного тома значит затереть диск ВМ мусором."""
    src = _backup_list_jsx()
    assert "{b.status === 'Succeeded' && (" not in src, "кнопка снова спрятана"
    assert "disabled={actionLoading !== null || !isDone(b)}" in src
    assert "title={isDone(b)" in src, "недоступная кнопка должна объяснять причину"


def test_backup_size_is_human_readable():
    """Размер приходит из PVC как есть — «22763326669». В списке это читалось
    как случайный номер, а не как объём."""
    src = _backup_list_jsx()
    assert "formatSize" in src
    assert "{formatSize(b.size)}" in src


def test_backup_block_is_not_smaller_than_everything_around_it():
    """Строка была 0.8rem против 0.9rem в соседних таблицах, а окно списка —
    250px, в которые помещались две копии из десяти. Список бэкапов читают
    так же, как таблицу снимков рядом, а не как подпись под графиком."""
    src = _backup_list_jsx()
    assert "maxHeight: '250px'" not in src
    assert "maxHeight: '460px'" in src
    assert "fontSize: '0.8rem'\n" not in src
