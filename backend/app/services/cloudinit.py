"""Вынос большого cloud-init в Secret.

KubeVirt отклоняет манифест, если inline `cloudInitNoCloud.userData` превышает
2048 байт:

    admission webhook denied the request: cloudInitNoCloud userdata exceeds
    2048 byte limit. Should use UserDataSecretRef for larger data.

Cloud-init маркетплейса содержит внутри себя docker-compose.yml и .env, поэтому
в лимит не влезает — без этого выноса приложения с базой данных (WordPress,
Nextcloud) вообще не создавались. Деплой из репозитория с длинным набором шагов
упирался в то же ограничение.

Небольшой userData оставляем inline: так меньше сущностей в кластере и не
ломается поведение обычных ВМ.
"""
import logging

logger = logging.getLogger("app.services.cloudinit")

# Порог с запасом относительно лимита KubeVirt (2048 байт).
INLINE_LIMIT_BYTES = 1900


def _userdata_volumes(manifest: dict):
    """Тома с inline cloud-init внутри манифеста ВМ."""
    spec = (manifest or {}).get("spec", {}).get("template", {}).get("spec", {})
    for volume in spec.get("volumes", []) or []:
        cloud_init = volume.get("cloudInitNoCloud")
        if isinstance(cloud_init, dict) and cloud_init.get("userData"):
            yield volume, cloud_init


def needs_secret(userdata: str) -> bool:
    return len(userdata.encode("utf-8")) > INLINE_LIMIT_BYTES


def externalize_cloudinit(k8s, manifest: dict, vm_name: str, namespace: str = "default") -> bool:
    """Переносит слишком большой cloud-init в Secret и правит манифест.

    Возвращает True, если перенос понадобился. Вызывать ДО создания ВМ:
    манифест должен уже ссылаться на существующий Secret.
    """
    moved = False
    for volume, cloud_init in list(_userdata_volumes(manifest)):
        userdata = cloud_init["userData"]
        if not needs_secret(userdata):
            continue
        secret_name = k8s.create_cloudinit_secret(vm_name, userdata, namespace)
        # Заменяем inline-данные ссылкой на Secret
        volume["cloudInitNoCloud"] = {"userDataSecretRef": {"name": secret_name}}
        moved = True
        logger.info(
            f"cloud-init для ВМ {vm_name} ({len(userdata.encode())} байт) вынесен "
            f"в Secret {secret_name}: inline-лимит KubeVirt — 2048 байт"
        )
    return moved
