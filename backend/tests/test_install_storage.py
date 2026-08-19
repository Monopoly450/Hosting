"""Установщик: хранилище со снимками из коробки, без Cloudflare."""
import os
import re


def _root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(_root(), *parts), encoding="utf-8") as f:
        return f.read()


def _install_sh():
    return _read("install.sh")


def _lvm_sh():
    return _read("scripts", "install-openebs-lvm.sh")


def test_vm_disks_land_on_a_snapshot_capable_class():
    """local-path по умолчанию означал, что снимки не работают НИКОГДА и
    молча: панель создаёт VirtualMachineSnapshot, показывает «создаётся», а
    он навсегда виснет в Pending — делать настоящий VolumeSnapshot нечем,
    local-path не CSI-драйвер. Пользователь видит «снимки не создаются» без
    единой ошибки в логах."""
    src = _install_sh()
    line = next(l for l in src.splitlines() if "storage_class=$(ask_value" in l)
    assert '"openebs-lvm")' in line, "класс дисков ВМ снова по умолчанию без снимков"


def test_failed_lvm_setup_does_not_leave_an_unusable_cluster():
    """У скрипта LVM стоит set -e: упади он на группе томов или на чарте —
    StorageClass в конце файла просто не выполнится. Панель тогда поднимется
    с классом, которого в кластере нет, и ни одна ВМ не создастся: PVC
    навсегда останется Pending. Проверяем результат, а не код возврата."""
    src = _install_sh()
    block = src[src.index('step "Настройка блочного хранилища'):]
    block = block[:block.index("# ============================== 9.")]

    assert "kubectl get storageclass openebs-lvm" in block, "результат установки не проверяется"
    assert "STORAGE_CLASS=local-path" in block, "нет отката на рабочий класс"
    assert "kubectl get volumesnapshotclass" in block, "класс снимков не проверяется"


def test_lvm_pool_is_sized_from_free_space():
    """40 ГБ были зашиты в скрипт намертво. Из этого пула нарезаются ВСЕ диски
    ВМ, поэтому на сервере с терабайтом место кончалось после четвёртой
    машины, причём как «PVC в Pending», а не как «место кончилось»."""
    install = _install_sh()
    lvm = _lvm_sh()

    assert "default_lvm_pool_gb()" in install
    assert "AEGIS_LVM_POOL_GB" in install, "размер не передаётся в скрипт LVM"
    assert 'POOL_GB="${AEGIS_LVM_POOL_GB:-40}"' in lvm
    assert 'truncate -s "${POOL_GB}G"' in lvm, "размер снова зашит в команду"
    # Мусор в переменной не должен молча превратиться в пул на 0 байт.
    assert "error \"AEGIS_LVM_POOL_GB должен быть целым числом" in lvm


def test_snapshot_class_is_created_by_the_installer():
    """Без VolumeSnapshotClass снимки не работают, и панель об этом узнаёт
    только в момент, когда пользователь их уже ждёт."""
    lvm = _lvm_sh()
    assert "kind: VolumeSnapshotClass" in lvm
    assert "snapshot.storage.kubernetes.io/is-default-class" in lvm, \
        "KubeVirt не указывает класс явно и полагается на дефолтный"


def test_lvm_installer_creates_restore_capable_thin_storage():
    install = _install_sh()
    lvm = _lvm_sh()
    assert 'thinProvision: "yes"' in lvm
    assert "modprobe dm_thin_pool" in lvm
    assert "modprobe dm_snapshot" in lvm
    assert "thin_pool_autoextend_threshold" in lvm
    assert "aegis-lvm-thin-monitor.timer" in lvm
    assert "--metadataprofile aegis-thinpool" in lvm
    assert "sed -ri" not in lvm, "инсталлятор не должен менять глобальный lvm.conf"
    assert "thin-provisioning-tools" in install
    assert '--version "$OPEN_EBS_LVM_CHART_VERSION"' in lvm
    assert "--atomic" in lvm


def test_existing_lvm_image_is_never_implicitly_truncated():
    lvm = _lvm_sh()
    existing = lvm.index('elif [ -e "$IMAGE" ]')
    create = lvm.index('truncate -s "${POOL_GB}G" "$IMAGE"')
    assert existing < create
    assert "Существующий образ $IMAGE найден; его размер не изменяется" in lvm
    assert "Не выполняю pvcreate поверх возможных данных" in lvm


def test_install_sh_verifies_the_exact_storage_release_after_upgrade():
    install = _install_sh()
    assert "LVM_SETUP_OK" in install
    assert 'deployed|lvm-localpv-${EXPECTED_LVM_CHART_VERSION}' in install
    assert "volumesnapshotclass openebs-lvm-snapshot" in install
    assert "aegis-lvm-thin-monitor.timer" in install


def test_installer_no_longer_mentions_cloudflare():
    """Туннель и выбор DNS-провайдера убраны из установщика по просьбе
    владельца: настройка требовала похода в чужую панель и ничего не давала
    там, где домен и так делегирован регистратору."""
    src = _install_sh()
    # Комментарии тоже считаются: вопрос был именно про упоминания в скрипте.
    assert not re.search(r"cloudflare", src, re.I), \
        "Cloudflare вернулся в установщик"
    assert "TIMEWEB_DNS_API_TOKEN" in src, "токен DNS должен остаться"
