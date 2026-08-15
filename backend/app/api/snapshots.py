import re
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List
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
                ready_to_use=s["ready_to_use"]
            ))
        return res
    except Exception as e:
        logger.error(f"Error listing snapshots for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_snapshot(vm_name: str, req: SnapshotCreateRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    
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
        ensure_any_storage_headroom(db)
    finally:
        db.close()

    # Без класса снимков томов снимок не получится физически, и провал этот
    # МОЛЧАЛИВЫЙ: объект VirtualMachineSnapshot создастся, панель покажет
    # «создаётся», а readyToUse не станет true никогда — KubeVirt не из чего
    # сделать настоящий VolumeSnapshot. Именно так это и выглядело: «снимки
    # не создаются». Отказываем сразу и объясняем, что делать.
    if not client.volume_snapshot_classes():
        raise HTTPException(
            status_code=400,
            detail="Снимки недоступны: в кластере нет ни одного VolumeSnapshotClass. "
                   "Хранилище по умолчанию (local-path) снимки не поддерживает — "
                   "это не CSI-драйвер. Установите блочное хранилище LVM: "
                   "sudo bash scripts/install-openebs-lvm.sh, затем создавайте "
                   "диски ВМ на классе openebs-lvm."
        )

    try:
        client.create_vm_snapshot(vm_name, full_snapshot_name)
        return SnapshotResponse(
            name=full_snapshot_name,
            creation_time="Только что создается",
            phase="Pending",
            ready_to_use=False
        )
    except Exception as e:
        logger.error(f"Error creating snapshot for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания снимка в Kubernetes: {e}")

@router.delete("/{vm_name}/{snapshot_name}")
def delete_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        client.delete_vm_snapshot(snapshot_name)
        return {"status": "Snapshot deletion request sent"}
    except Exception as e:
        logger.error(f"Error deleting snapshot {snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}/{snapshot_name}/restore")
def restore_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)

    # KubeVirt требует, чтобы ВМ была выключена: пока жив VirtualMachineInstance,
    # он отклонит VirtualMachineRestore. Раньше панель просто отдавала 400
    # «остановите ВМ» и перекладывала это на пользователя — при том что кнопка
    # отката всё равно перезагружает машину, и остановить её панель умеет сама.
    # Ровно так же уже устроено восстановление из бэкапа.
    was_running = False
    try:
        vm = client.get_vm(vm_name)
        was_running = vm.get("status") == "Running"
    except Exception as e:
        # Статус не прочитался — откат всё равно пробуем. Если ВМ на самом деле
        # запущена, откажет уже KubeVirt, и это попадёт в ответ ниже.
        logger.warning(f"Could not verify VM status: {e}")

    if was_running:
        logger.info(f"Авто-остановка ВМ {vm_name} перед откатом на снимок {snapshot_name}")
        try:
            client.stop_vm(vm_name)
        except Exception as e:
            logger.error(f"Не удалось остановить ВМ {vm_name} перед откатом: {e}")
            raise HTTPException(status_code=500, detail=f"Не удалось остановить ВМ перед откатом: {e}")
        if not client.wait_for_vm_stopped(vm_name):
            # Гость не погасился за отведённое время. Создавать откат сейчас
            # бессмысленно — KubeVirt его отклонит, а ВМ останется выключенной
            # без объяснений.
            raise HTTPException(
                status_code=409,
                detail="ВМ не успела выключиться за 2 минуты. Она остановлена — повторите откат.",
            )

    try:
        # restart_after: ВМ гасили только ради отката, и поднять её обратно —
        # обязанность панели. Откат идёт минутами, поэтому включает её воркер
        # по завершении (см. snapshot_restart_daemon), а не этот запрос.
        client.restore_vm_snapshot(vm_name, snapshot_name, restart_after=was_running)
        return {
            "status": "VM restore request sent successfully",
            "vm_stopped": was_running,
            "will_restart": was_running,
        }
    except Exception as e:
        logger.error(f"Error restoring snapshot {snapshot_name}: {e}")
        if was_running:
            # Откат не создался, а ВМ уже выключена нами. Возвращаем как было:
            # иначе пользователь получает ошибку И погашенную машину.
            try:
                client.start_vm(vm_name)
            except Exception as start_err:
                logger.error(f"ВМ {vm_name} осталась выключенной после неудачного отката: {start_err}")
        raise HTTPException(status_code=500, detail=f"Ошибка восстановления снимка в Kubernetes: {e}")
