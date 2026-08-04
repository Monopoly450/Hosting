"""Большой cloud-init должен уходить в Secret, а не в манифест.

KubeVirt отклоняет создание ВМ, если inline cloudInitNoCloud.userData больше
2048 байт. Cloud-init маркетплейса содержит docker-compose и .env, поэтому в
лимит не влезает — из-за этого приложения с базой данных (Nextcloud, WordPress)
не создавались вообще:

    admission webhook denied the request: cloudInitNoCloud userdata exceeds
    2048 byte limit. Should use UserDataSecretRef for larger data.
"""
import os
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cloudinit import (
    INLINE_LIMIT_BYTES, externalize_cloudinit, needs_secret,
)


class FakeK8s:
    def __init__(self):
        self.created = []

    def create_cloudinit_secret(self, name, userdata, namespace="default"):
        self.created.append({"name": name, "userdata": userdata, "ns": namespace})
        return f"{name}-cloudinit"


def manifest_with(userdata: str, networkdata: str = None) -> dict:
    cloud_init = {"userData": userdata}
    if networkdata is not None:
        cloud_init["networkData"] = networkdata
    return {
        "spec": {"template": {"spec": {"volumes": [
            {"name": "disk", "dataVolume": {"name": "vm1-disk"}},
            {"name": "cloudinit", "cloudInitNoCloud": cloud_init},
        ]}}}
    }


def cloud_init_of(manifest):
    return manifest["spec"]["template"]["spec"]["volumes"][1]["cloudInitNoCloud"]


# ------------------------------- порог --------------------------------------

def test_limit_is_below_kubevirt_hard_limit():
    """Порог должен быть строго меньше 2048 — иначе граничный случай упадёт."""
    assert INLINE_LIMIT_BYTES < 2048


def test_small_userdata_does_not_need_secret():
    assert needs_secret("#cloud-config\npackages:\n  - curl\n") is False


def test_large_userdata_needs_secret():
    assert needs_secret("#cloud-config\n" + "x" * 3000) is True


def test_limit_counts_bytes_not_characters():
    """Кириллица в комментариях cloud-init занимает по 2 байта — считать надо
    байты, иначе манифест снова упрётся в лимит KubeVirt."""
    text = "я" * 1200          # 1200 символов, но 2400 байт
    assert len(text) < INLINE_LIMIT_BYTES
    assert needs_secret(text) is True


# ------------------------------ вынос в Secret ------------------------------

def test_small_userdata_stays_inline():
    k8s = FakeK8s()
    m = manifest_with("#cloud-config\nruncmd:\n  - echo hi\n")
    assert externalize_cloudinit(k8s, m, "vm1") is False
    assert k8s.created == []
    assert "userData" in cloud_init_of(m)


def test_large_userdata_moved_to_secret():
    k8s = FakeK8s()
    big = "#cloud-config\n" + "y" * 4000
    m = manifest_with(big)

    assert externalize_cloudinit(k8s, m, "vm1") is True

    # содержимое ушло в Secret целиком и без изменений
    assert len(k8s.created) == 1
    assert k8s.created[0]["userdata"] == big
    assert k8s.created[0]["name"] == "vm1"

    # в манифесте осталась только ссылка
    ci = cloud_init_of(m)
    assert "userData" not in ci
    assert ci["secretRef"] == {"name": "vm1-cloudinit"}


def test_secret_reference_uses_the_field_kubevirt_actually_accepts():
    """В схеме CloudInitNoCloudSource поле называется secretRef.

    С userDataSecretRef (такого поля в схеме нет) Kubernetes молча отбрасывал
    неизвестный ключ, объект оказывался пустым, и валидатор отвечал
    «must have at least one userdatasource or one networkdatasource set».
    networkDataSecretRef относится к network-data и здесь не подходит.
    """
    m = manifest_with("#cloud-config\n" + "z" * 4000)
    externalize_cloudinit(FakeK8s(), m, "vm1")
    ci = cloud_init_of(m)

    assert "secretRef" in ci
    assert "userDataSecretRef" not in ci
    assert "networkDataSecretRef" not in ci
    # ссылка должна быть объектом с именем, а не строкой
    assert isinstance(ci["secretRef"], dict) and "name" in ci["secretRef"]


def test_secret_key_is_the_one_kubevirt_reads():
    """KubeVirt читает из Secret ключ userdata — под другим именем данные
    не подхватятся."""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "core", "k8s_client.py",
    )
    with open(src_path, encoding="utf-8") as f:
        src = f.read()

    block = src[src.find("def create_cloudinit_secret"):]
    assert 'string_data={"userdata"' in block[:900]


def test_network_data_survives_externalization():
    """Реальный баг: замена всего cloudInitNoCloud на {"secretRef": ...}
    стирала networkData, лежавший в том же объекте — ВМ теряла сеть у
    ЛЮБОГО шаблона тяжелее ~1900 байт (WordPress, LAMP с SSH-ключом, весь
    маркетплейс — там всегда docker-compose+.env). На Ubuntu пропажу
    маскировал собственный DHCP-фолбэк cloud-init; на остальных системах
    сеть не поднималась вообще — выглядело как «шаблоны работают только на
    Ubuntu», хотя дело было не в шаблоне и не в ОС, а в размере userData."""
    k8s = FakeK8s()
    network_config = "version: 2\nethernets:\n  stable-nic:\n    dhcp4: false\n    addresses: [172.20.0.55/24]\n"
    big = "#cloud-config\n" + "y" * 4000
    m = manifest_with(big, networkdata=network_config)

    assert externalize_cloudinit(k8s, m, "vm1") is True

    ci = cloud_init_of(m)
    assert "userData" not in ci
    assert ci["secretRef"] == {"name": "vm1-cloudinit"}
    assert ci["networkData"] == network_config, "networkData потерялся при выносе userData в Secret"


def test_metadata_also_survives_externalization():
    k8s = FakeK8s()
    m = manifest_with("#cloud-config\n" + "y" * 4000)
    cloud_init_of(m)["metaData"] = "instance-id: vm1\nlocal-hostname: vm1\n"
    externalize_cloudinit(k8s, m, "vm1")
    assert cloud_init_of(m)["metaData"] == "instance-id: vm1\nlocal-hostname: vm1\n"


def test_real_manifest_pipeline_keeps_network_after_externalization():
    """Сквозная проверка на настоящем generate_linux_manifest, а не на
    вручную собранном фикстурном манифесте — именно этот путь проходит
    воркер перед созданием ВМ (см. worker.py)."""
    from app.api.vms import generate_linux_manifest

    class Req:
        name = "wp-test"
        os_type = "rocky"
        cpu_cores = 2
        memory_gb = 2
        disk_gb = 20
        custom_image = None
        packages = None
        network_drives = None
        cloud_init_template = "wordpress"
        custom_user_data = None
        iso_url = None
        ssh_key = None
        static_ip = "172.20.0.55"
        cluster_network = None

    manifest = generate_linux_manifest(Req(), "pw123")
    k8s = FakeK8s()
    moved = externalize_cloudinit(k8s, manifest, "wp-test")

    ci = [v for v in manifest["spec"]["template"]["spec"]["volumes"]
          if "cloudInitNoCloud" in v][0]["cloudInitNoCloud"]

    if moved:
        assert "networkData" in ci, "networkData потерялся при выносе userData в Secret"
        assert "172.20.0.55/24" in ci["networkData"]
    else:
        # userData уместился inline — тогда и networkData обязан остаться на месте
        assert "172.20.0.55/24" in ci["networkData"]


def test_manifest_without_cloudinit_is_untouched():
    k8s = FakeK8s()
    m = {"spec": {"template": {"spec": {"volumes": [{"name": "disk"}]}}}}
    assert externalize_cloudinit(k8s, m, "vm1") is False
    assert k8s.created == []


def test_empty_manifest_does_not_crash():
    assert externalize_cloudinit(FakeK8s(), {}, "vm1") is False


# --------------------- реальные данные маркетплейса -------------------------

KUBEVIRT_HARD_LIMIT = 2048


@pytest.mark.parametrize("app_id", ["wordpress", "nextcloud"])
def test_apps_with_database_exceed_the_limit(app_id):
    """Приложения с отдельной БД (два сервиса в compose) в лимит не влезают —
    именно на них создание ВМ и падало."""
    from app.services import marketplace as mp

    app = mp.get_app(app_id)
    env = mp.add_public_url(mp.resolve_env(app, {}), "10.0.0.5", 28042)
    size = len(mp.build_marketplace_cloud_init(app, env, "pw").encode())

    assert size > KUBEVIRT_HARD_LIMIT, f"{app_id}: {size} байт"


def test_no_app_is_left_inline_above_the_limit():
    """Ключевая гарантия для всего каталога: после обработки в манифесте не
    остаётся inline-данных, которые KubeVirt отклонит."""
    from app.services import marketplace as mp

    for app in mp.CATALOG:
        env = mp.add_public_url(mp.resolve_env(app, {}), "10.0.0.5", 28042)
        userdata = mp.build_marketplace_cloud_init(app, env, "pw")

        m = manifest_with(userdata)
        externalize_cloudinit(FakeK8s(), m, f"{app['id']}-1")
        ci = cloud_init_of(m)

        inline = ci.get("userData")
        if inline is not None:
            assert len(inline.encode()) <= KUBEVIRT_HARD_LIMIT, (
                f"{app['id']}: {len(inline.encode())} байт осталось inline — "
                "KubeVirt отклонит создание ВМ"
            )
        else:
            assert "secretRef" in ci, f"{app['id']}: данные потерялись"


def test_marketplace_manifest_ends_up_with_secret_ref():
    """Сквозная проверка: cloud-init Nextcloud не остаётся inline."""
    from app.services import marketplace as mp

    app = mp.get_app("nextcloud")
    env = mp.add_public_url(mp.resolve_env(app, {}), "10.0.0.5", 28042)
    userdata = mp.build_marketplace_cloud_init(app, env, "pw")

    k8s = FakeK8s()
    m = manifest_with(userdata)
    assert externalize_cloudinit(k8s, m, "nextcloud-1") is True
    assert "secretRef" in cloud_init_of(m)


def test_worker_externalizes_before_creating_vm():
    """Порядок важен: Secret должен существовать до создания ВМ."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "worker.py"
    )
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert src.count("externalize_cloudinit(k8s, manifest, task.name)") == 2, (
        "вынос cloud-init нужен в обоих путях: создание и клонирование"
    )
    for block in src.split("k8s.create_vm_from_manifest(manifest)")[:-1]:
        assert "externalize_cloudinit" in block[-400:], (
            "externalize_cloudinit должен вызываться перед созданием ВМ"
        )
