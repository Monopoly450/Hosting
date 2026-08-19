import re
import logging
import time
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.models.models import User
from app.core.auth import get_current_user
from app.core.k8s_client import K8sClient
from app.api.vms import check_vm_ownership

router = APIRouter()
logger = logging.getLogger("app.api.snapshots")

def get_k8s_client():
    return K8sClient()

class SnapshotCreateRequest(BaseModel):
    name: str = Field(..., description="Имя снимка (a-z, 0-9, -)")

class SnapshotResponse(BaseModel):
    name: str
    creation_time: str
    phase: str
    ready_to_use: bool
    # Захвачен ли диск. KubeVirt считает снимок успешным и тогда, когда снял
    # одно описание ВМ, а том положил в excludedVolumes — панель показывала
    # такой снимок как «Готов», хотя откатывать им нечего.
    has_disk: bool = True
    excluded_volumes: List[str] = []
    # Только те исключённые тома, за которыми стоял настоящий диск.
    # excluded_volumes сам по себе ни о чём не говорит: cloudinitdisk есть у
    # каждой ВМ и исключается всегда.
    missing_volumes: List[str] = []
    # Ход создания. Процент у снимка грубый — по числу снятых томов, потому
    # что тонкого KubeVirt не считает (см. K8sClient._snapshot_progress).
    progress_percent: Optional[int] = None
    volumes_ready: int = 0
    volumes_total: int = 0
    error: Optional[str] = None


def _snapshot_for_vm(client: K8sClient, vm_name: str, snapshot_name: str) -> dict:
    """Ищет снимок только среди снимков указанной ВМ."""
    try:
        return next(
            s for s in client.list_vm_snapshots(vm_name)
            if s["name"] == snapshot_name
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="Снимок не найден")

def _unsupported_reason(support: dict) -> str:
    """Почему снимки этой ВМ невозможны — одним текстом.

    Один и тот же текст нужен и отказу при создании, и предупреждению в
    панели. Держать две формулировки — верный способ, чтобы они разошлись.
    """
    if not support["storage_classes"]:
        return "Не удалось определить класс хранения дисков этой ВМ."
    thin = [
        u["storage_class"] for u in support["unsupported"]
        if u.get("reason") == "thin_required"
    ]
    wrong_driver = [
        u for u in support["unsupported"]
        if u.get("reason") != "thin_required"
    ]
    if thin and not wrong_driver:
        return (
            f"Класс {', '.join(thin)} создаёт thick LVM-тома. OpenEBS "
            "может снять такой том, но не может восстановить его из "
            "снимка. Пересоздайте LVM и ВМ через обновлённый "
            "scripts/install-openebs-lvm.sh: он включает thinProvision."
        )

    bad = ", ".join(
        f"{u['storage_class']} (провизионер {u['provisioner'] or 'неизвестен'})"
        for u in wrong_driver
    )
    drivers = ", ".join(support["snapshot_drivers"]) or "нет ни одного"
    return (
        f"Диск этой ВМ лежит на {bad}, а снимки умеют делать только драйверы, "
        f"для которых в кластере есть VolumeSnapshotClass ({drivers}). "
        "Снимок создастся «успешным», но без диска — откатить им ничего нельзя. "
        "Установите блочное хранилище LVM: sudo bash scripts/install-openebs-lvm.sh, "
        "укажите в .env STORAGE_CLASS=openebs-lvm и пересоздайте ВМ — "
        "диск уже существующей машины на другой класс не переедет."
    )


@router.get("/{vm_name}/support")
def snapshot_support(vm_name: str, client: K8sClient = Depends(get_k8s_client),
                     current_user: User = Depends(get_current_user)):
    """Можно ли вообще снимать снимки с дисков этой ВМ.

    Панель спрашивает это ДО того, как пользователь нажмёт «Создать снимок».
    Без этого он видел ноль процентов, который не двигается (двигаться ему
    нечем — тома в снимке нет), а через минуту вместо результата получал
    «Без диска». Причину надо называть заранее, а не показывать полосу,
    которая заведомо не дойдёт до конца.
    """
    check_vm_ownership(vm_name, current_user)
    try:
        support = client.snapshot_support(vm_name)
    except Exception as e:
        logger.error(f"Error checking snapshot support for {vm_name}: {e}")
        # Панель не должна ломаться из-за диагностики: не смогли проверить —
        # значит не мешаем, отказ при создании всё равно сработает.
        return {"supported": True, "reason": None}
    return {
        "supported": support["supported"],
        "reason": None if support["supported"] else _unsupported_reason(support),
        "storage_classes": support["storage_classes"],
    }


@router.get("/{vm_name}", response_model=List[SnapshotResponse])
def list_snapshots(vm_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        snaps = client.list_vm_snapshots(vm_name)
        res = []
        for s in snaps:
            # Превращаем время в читаемый формат
            time_str = s["creation_time"] or "Unknown"
            if time_str and time_str != "Unknown":
                # Формат UTC ISO
                time_str = time_str.replace("T", " ").replace("Z", "")
            res.append(SnapshotResponse(
                name=s["name"],
                creation_time=time_str,
                phase=s["phase"],
                ready_to_use=s["ready_to_use"],
                has_disk=s.get("has_disk", True),
                excluded_volumes=s.get("excluded_volumes", []),
                missing_volumes=s.get("missing_volumes", []),
                progress_percent=s.get("progress_percent"),
                volumes_ready=s.get("volumes_ready", 0),
                volumes_total=s.get("volumes_total", 0),
                error=s.get("error"),
            ))
        return res
    except Exception as e:
        logger.error(f"Error listing snapshots for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_snapshot(vm_name: str, req: SnapshotCreateRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        client.ensure_no_backup_operation(vm_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    
    if not re.match(r"^[a-z0-9-]{3,32}$", req.name):
        raise HTTPException(
            status_code=400,
            detail="Имя снимка должно содержать только строчные латинские буквы, цифры и дефис."
        )

    # Имя снапшота в Kubernetes
    full_snapshot_name = f"snap-{vm_name}-{req.name}"

    # Снимок — это VirtualMachineSnapshot, дифференциальный объект: в отличие
    # от бэкапа (полного клона PVC) у него нет известного заранее размера —
    # он растёт по мере изменений на диске ПОСЛЕ создания снимка. Поэтому
    # здесь не проверяется конкретное число ГБ (проверять было бы нечего),
    # а только то, что хранилище не забито под ноль совсем: делать снимок
    # некуда расти на уже исчерпанном пуле — риск, что он тут же откажет
    # или испортит данные вместо того чтобы честно не создаться.
    from app.db import SessionLocal
    from app.core.capacity import lock_host_capacity, ensure_any_storage_headroom
    db = SessionLocal()
    try:
        lock_host_capacity(db)
        ensure_any_storage_headroom(db, k8s=client)
    finally:
        db.close()

    # Проверяем не «есть ли в кластере хоть какой-нибудь класс снимков», а
    # найдётся ли класс под провизионер диска ИМЕННО ЭТОЙ ВМ.
    #
    # Разница не теоретическая, на неё и напоролись. После установки LVM в
    # кластере появляется VolumeSnapshotClass с driver local.csi.openebs.io,
    # и проверка «есть хоть один» проходит. Но диск ВМ, созданной раньше,
    # остался на local-path с провизионером rancher.io/local-path. Совпадения
    # нет — KubeVirt не падает, а молча кладёт том в excludedVolumes и всё
    # равно ставит снимку phase: Succeeded. Панель показывает «Готов», откат
    # проходит без ошибок и возвращает описание ВМ, а диск не трогает:
    # установленное после снимка приложение остаётся на месте. Пользователь
    # при этом уверен, что точка отката у него есть.
    support = client.snapshot_support(vm_name)
    if not support["supported"]:
        raise HTTPException(status_code=400, detail="Снимки недоступны: " + _unsupported_reason(support))

    try:
        client.create_vm_snapshot(vm_name, full_snapshot_name)
        return SnapshotResponse(
            name=full_snapshot_name,
            creation_time="Только что создается",
            phase="Pending",
            ready_to_use=False,
            progress_percent=0,
        )
    except Exception as e:
        logger.error(f"Error creating snapshot for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания снимка в Kubernetes: {e}")

@router.delete("/{vm_name}/{snapshot_name}")
def delete_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        client.ensure_no_backup_operation(vm_name)
        _snapshot_for_vm(client, vm_name, snapshot_name)
        client.delete_vm_snapshot(snapshot_name)
        return {"status": "Snapshot deletion request sent"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting snapshot {snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}/{snapshot_name}/restore")
def restore_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        client.ensure_no_backup_operation(vm_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Откат снимком без диска не возвращает ничего заметного: KubeVirt честно
    # применит описание ВМ, ответит успехом — и на этом всё. Именно так и
    # выглядело «сделал откат, а приложение осталось». Лучше отказать, чем
    # выдать за откат то, что им не является.
    snap = _snapshot_for_vm(client, vm_name, snapshot_name)
    if snap.get("phase") != "Succeeded":
        raise HTTPException(
            status_code=409,
            detail=(
                "Снимок ещё не готов к откату "
                f"(статус: {snap.get('phase') or 'Unknown'})."
            ),
        )
    if not snap.get("ready_to_use"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Снимок завершён, но недоступен для отката. "
                "Kubernetes не подтверждает готовность его дискового снимка; "
                "возможно, связанный VolumeSnapshot был удалён или повреждён."
            ),
        )
    if not snap.get("has_disk", True):
        excluded = ", ".join(snap.get("missing_volumes") or snap.get("excluded_volumes") or []) or "диск"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Откат невозможен: в этом снимке нет диска ({excluded} не попал в снимок). "
                "Снят только конфиг ВМ — хранилище её диска не умеет делать снимки, "
                "поэтому откат вернул бы описание машины, но не её содержимое. "
                "Такой снимок можно только удалить."
            ),
        )

    # Старый снимок мог быть создан до перехода openebs-lvm на thin. Его
    # статус всё равно выглядит успешным, но OpenEBS не умеет восстановить
    # thick-снимок. Проверяем реальный PV повторно непосредственно перед
    # разрушительной операцией и возвращаем понятную причину вместо 500.
    support = client.snapshot_support(vm_name)
    if not support["supported"]:
        raise HTTPException(
            status_code=400,
            detail="Откат недоступен: " + _unsupported_reason(support),
        )

    # targetReadinessPolicy=StopTarget позволяет сначала записать durable
    # VirtualMachineRestore, а уже затем безопасно остановить ВМ контроллером.
    # Поэтому crash/timeout HTTP-процесса больше не оставляет машину погашенной
    # в окне между ручным stop и созданием restore.
    try:
        vm = client.get_vm(vm_name)
    except Exception as e:
        # StopTarget действительно остановит target. Без надёжно прочитанного
        # desired state нельзя решить, ставить ли durable restart-аннотацию:
        # продолжение здесь могло навсегда погасить работающую ВМ.
        logger.error(f"Could not read VM power state before restore: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось определить желаемое состояние ВМ перед откатом: {e}",
        )

    desired_state = vm.get("desired_state")
    if desired_state is not None:
        was_running = desired_state == "Running"
    else:
        # Совместимость с клиентами старой версии: переходные VMI-фазы тоже
        # означают, что пользователь оставил desired state включённым.
        was_running = vm.get("status") in {
            "Running", "Starting", "Scheduled", "Pending", "Paused",
        }

    restore_name = f"restore-{snapshot_name}-{time.time_ns()}"
    try:
        action_guard = client.acquire_vm_action_guard(
            vm_name, "snapshot-restore"
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    try:
        # restart_after: ВМ гасили только ради отката, и поднять её обратно —
        # обязанность панели. Откат идёт минутами, поэтому включает её воркер
        # по завершении (см. snapshot_restart_daemon), а не этот запрос.
        client.restore_vm_snapshot(
            vm_name, snapshot_name, restart_after=was_running,
            restore_name=restore_name,
        )
        try:
            client.clear_vm_action_guard(vm_name, action_guard)
        except Exception as clear_error:
            logger.warning(
                f"Restore {restore_name} создан, но временный guard не снят: "
                f"{clear_error}"
            )
        return {
            "status": "VM restore request sent successfully",
            "vm_stopped": was_running,
            "will_restart": was_running,
        }
    except Exception as e:
        logger.error(f"Error restoring snapshot {snapshot_name}: {e}")
        # Потерянный ответ create неоднозначен. Если объект уже есть, операция
        # реально идёт — не сообщаем пользователю ложную ошибку и не запускаем
        # target посреди отката.
        try:
            existing = client.get_vm_snapshot_restore(restore_name)
            try:
                client.clear_vm_action_guard(vm_name, action_guard)
            except Exception as clear_error:
                logger.warning(
                    f"Не удалось снять guard найденного restore {restore_name}: "
                    f"{clear_error}"
                )
            return {
                "status": "VM restore request accepted",
                "vm_stopped": was_running,
                "will_restart": was_running,
                "reconciled": True,
                "complete": bool((existing.get("status") or {}).get("complete")),
            }
        except Exception as read_error:
            if getattr(read_error, "status", None) == 404:
                try:
                    client.clear_vm_action_guard(vm_name, action_guard)
                except Exception as clear_error:
                    logger.warning(
                        f"Не удалось снять guard не созданного restore "
                        f"{restore_name}: {clear_error}"
                    )
            else:
                logger.error(
                    f"Не удалось проверить создание restore {restore_name}: {read_error}"
                )
        raise HTTPException(status_code=500, detail=f"Ошибка восстановления снимка в Kubernetes: {e}")
