"""Потоковые S3-копии всех дисков ВМ через KubeVirt Export API.

Фоновые операции хранятся в PostgreSQL и продолжаются после рестарта worker.
Снимки здесь — полные дисковые точки восстановления, без CSI-зависимости.
"""
import copy
import json
import logging
import os
import secrets
import ssl
import time
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlsplit

import urllib3
from fastapi import HTTPException
from kubernetes import client as kube
from kubernetes.client.rest import ApiException
from minio import Minio
from sqlalchemy import or_

from app.db import SessionLocal
from app.models.models import VMArchive, VMTask
from app.services.backup_storage import ensure_backup_bucket

logger = logging.getLogger(__name__)
ACTIVE = ("Pending", "Exporting", "Uploading", "Finalizing")


def s3_client():
    from app.api.s3 import get_minio_client
    return get_minio_client()


def wants_running(k8s, name):
    vm = k8s.get_vm(name)
    return vm.get("desired_state", vm.get("status")) in {"Running", "Starting", "Scheduled", "Pending", "Paused"}


def disk_volumes(vm):
    spec = vm.get("spec", {}).get("template", {}).get("spec", {})
    disks = {d["name"] for d in spec.get("domain", {}).get("devices", {}).get("disks", [])
             if "disk" in d or "lun" in d}
    result = []
    for volume in spec.get("volumes", []):
        pvc = volume.get("persistentVolumeClaim", {}).get("claimName") or volume.get("dataVolume", {}).get("name")
        if pvc and volume.get("name") in disks:
            result.append({"volume_name": volume["name"], "pvc": pvc})
    if not result:
        raise ValueError("Не найдены постоянные диски ВМ для копирования в S3")
    return result


def get_task(db, vm_name, lock=False):
    query = db.query(VMTask).filter(VMTask.name == vm_name)
    task = (query.with_for_update() if lock else query).first()
    if not task:
        raise HTTPException(status_code=404, detail="ВМ не найдена")
    if task.os_type == "windows":
        raise HTTPException(status_code=400, detail="Бэкапы и снимки для Windows отключены")
    if not task.owner_id:
        raise HTTPException(status_code=400, detail="У ВМ нет владельца для S3-бакета")
    return task


def assert_idle(db, vm_name):
    busy = db.query(VMArchive).filter(
        VMArchive.vm_name == vm_name,
        or_(VMArchive.status.in_(ACTIVE), VMArchive.operation.isnot(None)),
    ).first()
    if busy:
        raise HTTPException(status_code=409, detail="Для ВМ уже выполняется операция S3")


def enqueue(vm_name, kind, k8s, label=None, retention=None, db=None, schedule_id=None):
    own_session = db is None
    db = db or SessionLocal()
    try:
        task = get_task(db, vm_name, lock=True)
        assert_idle(db, vm_name)
        k8s.ensure_no_backup_operation(vm_name)
        vm = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", vm_name)
        volumes = disk_volumes(vm)
        # Проверяем API до постановки в очередь и выключения гостя.
        k8s.custom_api.list_namespaced_custom_object(
            "export.kubevirt.io", "v1beta1", "default", "virtualmachineexports", limit=1)
        s3 = s3_client()
        bucket = ensure_backup_bucket(db, task.owner_id, s3)
        name = f"s3-{kind}-{uuid.uuid4().hex}"
        record = VMArchive(
            name=name, vm_name=vm_name, owner_id=task.owner_id, kind=kind,
            bucket=bucket, prefix=f"vms/{task.id}/{kind}/{name}/",
            status="Pending", progress=0, retention=retention,
            manifest={"label": label or name, "vm_id": task.id, "vm_uid": vm["metadata"]["uid"],
                      "volumes": volumes, "vm_spec": copy.deepcopy(vm["spec"]), "schedule_id": schedule_id},
        )
        db.add(record)
        db.commit()
        return {"backup_name": name, "name": name, "status": "Pending", "phase": "Pending",
                "creation_time": datetime.utcnow().isoformat(), "ready_to_use": False,
                "has_disk": True, "progress_percent": 0, "storage": "s3", "bucket": bucket,
                "will_restart": wants_running(k8s, vm_name)}
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error))
    finally:
        if own_session:
            db.close()


def find(db, task, name, kind):
    record = db.query(VMArchive).filter(
        VMArchive.name == name, VMArchive.vm_name == task.name,
        VMArchive.owner_id == task.owner_id, VMArchive.kind == kind,
    ).first()
    if not record or (record.manifest or {}).get("vm_id") != task.id:
        raise HTTPException(status_code=404, detail="S3-копия не найдена для этой ВМ")
    return record


def list_archives(vm_name, kind):
    with SessionLocal() as db:
        task = get_task(db, vm_name)
        rows = db.query(VMArchive).filter(VMArchive.vm_name == vm_name,
                    VMArchive.owner_id == task.owner_id, VMArchive.kind == kind).order_by(VMArchive.created_at.desc()).all()
        result = []
        for row in rows:
            if (row.manifest or {}).get("vm_id") != task.id:
                continue
            ready = row.status == "Succeeded" and not row.operation
            phase = row.restore_state if row.operation and row.restore_state else row.status
            result.append({
                "name": row.name, "label": (row.manifest or {}).get("label", row.name),
                "creation_time": row.created_at.isoformat(), "status": phase, "phase": phase,
                "created_at": row.created_at.isoformat() + "Z",
                "ready_to_use": ready, "has_disk": bool((row.manifest or {}).get("disks")),
                "progress": f"{row.progress or 0}%", "progress_percent": row.progress or 0,
                "size": sum(d.get("bytes", 0) for d in (row.manifest or {}).get("disks", [])),
                "storage": "s3", "bucket": row.bucket, "error": row.error, "detail": row.error,
                "restore_state": row.restore_state,
            })
        return result


def delete_archive(vm_name, name, kind):
    with SessionLocal() as db:
        task = get_task(db, vm_name, lock=True)
        row = find(db, task, name, kind)
        if row.operation or row.status in ACTIVE:
            raise HTTPException(status_code=409, detail="Дождитесь завершения операции перед удалением копии")
        s3 = s3_client()
        for item in s3.list_objects(row.bucket, prefix=row.prefix, recursive=True):
            s3.remove_object(row.bucket, item.object_name)
        db.delete(row)
        db.commit()
    return {"status": "deleted"}


def enqueue_restore(vm_name, name, kind, k8s):
    with SessionLocal() as db:
        task = get_task(db, vm_name, lock=True)
        assert_idle(db, vm_name)
        row = find(db, task, name, kind)
        if row.status != "Succeeded" or not row.manifest.get("disks"):
            raise HTTPException(status_code=409, detail="Копия ещё не готова для восстановления")
        k8s.ensure_no_backup_operation(vm_name)
        raw = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", vm_name)
        if raw["metadata"]["uid"] != row.manifest["vm_uid"]:
            raise HTTPException(status_code=409, detail="Исходная ВМ была пересоздана; эта копия относится к другой ВМ")
        if {v["volume_name"] for v in disk_volumes(raw)} != {d["volume_name"] for d in row.manifest["disks"]}:
            raise HTTPException(status_code=409, detail="Состав дисков изменился после копирования; автоматический откат запрещён")
        s3 = s3_client()
        for disk in row.manifest["disks"]:
            obj = s3.stat_object(row.bucket, disk["object"])
            if obj.size != disk["bytes"] or obj.etag != disk["etag"]:
                raise HTTPException(status_code=409, detail="S3-копия повреждена или изменена")
        from app.core.capacity import lock_host_capacity, ensure_storage_capacity
        lock_host_capacity(db)
        from kubernetes.utils.quantity import parse_quantity
        required = sum(float(parse_quantity(d["claim"]["resources"]["requests"]["storage"])) / (1024 ** 3)
                       for d in row.manifest["disks"])
        ensure_storage_capacity(db, extra_gb=required, k8s=k8s)
        row.operation = "restore-" + uuid.uuid4().hex
        row.restore_state = "Pending"
        row.restore_data = {"reserved_gb": required}
        row.error = None
        db.commit()
        return {"status": "Pending", "will_restart": wants_running(k8s, vm_name)}


def _wait_export(k8s, row):
    name = row.name
    api = k8s.custom_api
    try:
        export = api.get_namespaced_custom_object("export.kubevirt.io", "v1beta1", "default", "virtualmachineexports", name)
    except ApiException as error:
        if error.status != 404:
            raise
        try:
            k8s.core_api.read_namespaced_secret(name, "default")
        except ApiException as secret_error:
            if secret_error.status != 404:
                raise
            k8s.core_api.create_namespaced_secret("default", kube.V1Secret(
                metadata=kube.V1ObjectMeta(name=name), string_data={"token": secrets.token_urlsafe(32)},
            ))
        export = api.create_namespaced_custom_object("export.kubevirt.io", "v1beta1", "default", "virtualmachineexports", {
            "apiVersion": "export.kubevirt.io/v1beta1", "kind": "VirtualMachineExport",
            "metadata": {"name": name},
            "spec": {"source": {"apiGroup": "kubevirt.io", "kind": "VirtualMachine", "name": row.vm_name},
                     "tokenSecretRef": name, "ttlDuration": "24h"},
        })
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        export = api.get_namespaced_custom_object("export.kubevirt.io", "v1beta1", "default", "virtualmachineexports", name)
        status = export.get("status", {})
        if status.get("phase") == "Ready":
            import base64
            token = k8s.core_api.read_namespaced_secret(name, "default").data["token"]
            return status, base64.b64decode(token).decode()
        if status.get("phase") == "Skipped":
            raise RuntimeError("KubeVirt не нашёл дисков для S3-экспорта")
        time.sleep(3)
    raise RuntimeError("Экспорт дисков не готов за 10 минут; проверьте VMExport и поды экспортера")


def _open_export(k8s, status, link, token):
    parsed = urlsplit(link)
    expected = status["serviceName"] + ".default.svc"
    if parsed.scheme != "https" or parsed.hostname not in {expected, expected + ".cluster.local"}:
        raise RuntimeError("Некорректный внутренний адрес экспортера")
    service = k8s.core_api.read_namespaced_service(status["serviceName"], "default")
    context = ssl.create_default_context(cadata=status["links"]["internal"]["cert"])
    pool = urllib3.HTTPSConnectionPool(
        service.spec.cluster_ip, port=parsed.port or 443, ssl_context=context,
        assert_hostname=parsed.hostname, server_hostname=parsed.hostname,
        timeout=urllib3.Timeout(connect=30, read=120), retries=False,
    )
    response = pool.request("GET", parsed.path, preload_content=False, redirect=False,
                            headers={"x-kubevirt-export-token": token, "Host": parsed.hostname})
    if response.status != 200:
        response.close()
        pool.close()
        raise RuntimeError(f"Экспортер диска вернул HTTP {response.status}")
    return pool, response


def _capture(db, k8s, row):
    if not row.operation:
        row.operation = row.name
        row.restart_vm = wants_running(k8s, row.vm_name)
        db.commit()
    vm = k8s.acquire_s3_operation(row.vm_name, row.operation)
    if vm["metadata"]["uid"] != row.manifest["vm_uid"]:
        raise RuntimeError("Исходная ВМ была удалена и пересоздана")
    if row.status == "Pending":
        row.manifest = {**row.manifest, "vm_spec": copy.deepcopy(vm["spec"]), "volumes": disk_volumes(vm)}
        db.commit()
    if row.status == "Finalizing":
        _finish(db, k8s, row)
        return
    # Проверяем S3 до выключения ВМ.
    s3 = s3_client()
    if not s3.bucket_exists(row.bucket):
        raise RuntimeError("S3-бакет резервных копий недоступен")
    from app.core.capacity import host_totals
    from kubernetes.utils.quantity import parse_quantity
    size_gb = sum(float(parse_quantity(k8s.core_api.read_namespaced_persistent_volume_claim(
        v["pvc"], "default").spec.resources.requests["storage"])) / 1024 ** 3 for v in row.manifest["volumes"])
    if host_totals()["disk_free_gb"] < size_gb + 5:
        raise RuntimeError("Недостаточно места на диске MinIO для полной S3-копии и резерва хоста (5 ГБ)")
    row.status = "Exporting"
    db.commit()
    _stop(k8s, row.vm_name)
    status, token = _wait_export(k8s, row)
    links = {v["name"]: v for v in status["links"]["internal"]["volumes"]}
    disks = []
    for i, volume in enumerate(row.manifest["volumes"]):
        formats = (links.get(volume["volume_name"]) or links.get(volume["pvc"], {})).get("formats", [])
        url = next((f["url"] for f in formats if f["format"] == "raw"), None)
        if not url:
            raise RuntimeError(f"Нет полного образа диска {volume['pvc']} в экспорте")
        pvc = k8s.core_api.read_namespaced_persistent_volume_claim(volume["pvc"], "default")
        claim = {"accessModes": pvc.spec.access_modes, "volumeMode": pvc.spec.volume_mode or "Filesystem",
                 "storageClassName": pvc.spec.storage_class_name,
                 "resources": {"requests": {"storage": pvc.spec.resources.requests["storage"]}}}
        key = row.prefix + f"disk-{i}.img"
        row.status = "Uploading"
        db.commit()
        pool, stream = _open_export(k8s, status, url, token)
        try:
            s3.put_object(row.bucket, key, stream, length=-1, part_size=64 * 1024 ** 2,
                          content_type="application/octet-stream", num_parallel_uploads=2)
        finally:
            stream.close()
            stream.release_conn()
            pool.close()
        obj = s3.stat_object(row.bucket, key)
        if obj.size <= 0:
            raise RuntimeError("Экспортер вернул пустой диск")
        disks.append({**volume, "claim": claim, "object": key, "bytes": obj.size, "etag": obj.etag})
        row.progress = int((i + 1) * 95 / len(row.manifest["volumes"]))
        db.commit()
    row.manifest = {**row.manifest, "disks": disks, "format_version": 1}
    data = json.dumps(row.manifest, ensure_ascii=False).encode()
    s3.put_object(row.bucket, row.prefix + "manifest.json", BytesIO(data), len(data), content_type="application/json")
    row.status = "Finalizing"
    db.commit()
    _finish(db, k8s, row)


def _delete_export(k8s, row):
    try:
        k8s.custom_api.delete_namespaced_custom_object("export.kubevirt.io", "v1beta1", "default", "virtualmachineexports", row.name)
    except ApiException as error:
        if error.status != 404:
            raise
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pods = k8s.core_api.list_namespaced_pod("default").items
        if not any(any(ref.kind == "VirtualMachineExport" and ref.name == row.name
                       for ref in (pod.metadata.owner_references or [])) for pod in pods):
            break
        time.sleep(2)
    else:
        raise RuntimeError("Экспортер ещё использует диск; повторю завершение операции")
    try:
        k8s.core_api.delete_namespaced_secret(row.name, "default")
    except ApiException as error:
        if error.status != 404:
            raise


def _finish(db, k8s, row):
    _delete_export(k8s, row)
    try:
        current = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", row.vm_name)
    except ApiException as error:
        if error.status != 404:
            raise
        current = None
    if not current or current["metadata"]["uid"] != row.manifest["vm_uid"]:
        # Никогда не запускаем другую ВМ, занявшую то же имя.
        row.operation = None
        row.status = "Failed"
        row.error = "Исходная ВМ удалена или пересоздана"
        db.commit()
        return
    if row.restore_state == "Failed" and (row.restore_data or {}).get("switched"):
        # Старый worker ошибочно помечал завершённый импорт Failed из-за
        # start -> 409. Восстанавливаем финализацию только при подтверждённом
        # переключении ВСЕХ дисков той же ВМ; чужие/старые диски не трогаем.
        expected = {disk["volume_name"]: f"{row.operation}-disk-{i}"
                    for i, disk in enumerate(row.manifest.get("disks", []))}
        attached = {disk["volume_name"]: disk["pvc"] for disk in disk_volumes(current)}
        if expected and attached == expected:
            row.restore_state = "Finalizing"
            row.error = None
            db.commit()
    if row.restore_state == "Failed":
        attached = {d["pvc"] for d in disk_volumes(current)}
        for i, _disk in enumerate(row.manifest["disks"]):
            target = f"{row.operation}-disk-{i}"
            if target in attached:
                continue  # PATCH мог выполниться, даже если ответ потерян.
            try:
                k8s.custom_api.delete_namespaced_custom_object("cdi.kubevirt.io", "v1beta1", "default", "datavolumes", target)
            except ApiException as error:
                if error.status != 404:
                    raise
    vm_status = k8s.get_vm(row.vm_name).get("status")
    if row.restart_vm and vm_status != "Running":
        if vm_status not in {"Starting", "Scheduling", "Scheduled", "Provisioning"}:
            try:
                k8s.start_vm(row.vm_name)
            except ApiException as error:
                if error.status != 409 or "VM is already running" not in (error.body or ""):
                    raise
                # Между чтением статуса и start ВМ уже могла запуститься.
                # Это не сбой импорта: следующий тик проверит Running.
        return  # следующий тик дождётся Running перед снятием блокировки
    k8s.clear_s3_operation(row.vm_name, row.operation)
    row.operation = None
    if row.status == "Finalizing":
        row.status = "Succeeded"
        row.progress = 100
        row.error = None
    if row.restore_state == "Finalizing":
        row.restore_state = None
        row.error = None
    db.commit()
    schedule_id = (row.manifest or {}).get("schedule_id")
    if schedule_id:
        from app.models.models import BackupSchedule
        schedule = db.get(BackupSchedule, schedule_id)
        if schedule and schedule.last_status == "queued":
            schedule.last_status = "success" if row.status == "Succeeded" else "error: S3-копирование не завершено"
            db.commit()
    if row.status == "Succeeded" and row.retention and row.restore_state != "Failed":
        try:
            _prune(db, row)
        except Exception:
            db.rollback()
            logger.exception("Не удалось удалить старые S3-копии; готовый архив сохранён")


def _stop(k8s, name):
    vm = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", name)
    spec = vm.get("spec", {})
    if (spec.get("running") or spec.get("runStrategy") in {"Always", "RerunOnFailure", "Once"}
            or k8s.get_vm(name).get("status") == "Running"):
        k8s.stop_vm(name)
    if not k8s.wait_for_vm_stopped(name):
        raise RuntimeError("ВМ не остановилась для целостной S3-копии")


def _prune(db, row):
    copies = db.query(VMArchive).filter(VMArchive.vm_name == row.vm_name,
        VMArchive.owner_id == row.owner_id, VMArchive.kind == row.kind,
        VMArchive.status == "Succeeded", VMArchive.operation.is_(None)).order_by(VMArchive.created_at.desc()).all()
    s3 = s3_client()
    for old in copies[row.retention:]:
        for obj in s3.list_objects(old.bucket, prefix=old.prefix, recursive=True):
            s3.remove_object(old.bucket, obj.object_name)
        db.delete(old)
    db.commit()


def _restore(db, k8s, row):
    # Оригиналы дисков остаются до успешного импорта и атомарного переключения.
    vm = k8s.acquire_s3_operation(row.vm_name, row.operation)
    if vm["metadata"]["uid"] != row.manifest["vm_uid"]:
        raise RuntimeError("Исходная ВМ была пересоздана")
    if row.restore_state == "Pending":
        row.restart_vm = wants_running(k8s, row.vm_name)
        originals = disk_volumes(vm)
        row.restore_data = {**row.restore_data, "originals": originals, "vm_spec": vm["spec"], "targets": [], "switched": False}
        row.restore_state = "Importing"
        db.commit()
    if row.restore_state == "Finalizing":
        _finish(db, k8s, row)
        return
    _stop(k8s, row.vm_name)
    from app.api.vms import get_host_ip
    download = Minio(f"{get_host_ip()}:9000", access_key=os.environ["MINIO_ROOT_USER"],
                     secret_key=os.environ["MINIO_ROOT_PASSWORD"], secure=False)
    targets = []
    for i, disk in enumerate(row.manifest["disks"]):
        target = f"{row.operation}-disk-{i}"
        targets.append({"volume_name": disk["volume_name"], "pvc": target})
        try:
            dv = k8s.custom_api.get_namespaced_custom_object("cdi.kubevirt.io", "v1beta1", "default", "datavolumes", target)
        except ApiException as error:
            if error.status != 404:
                raise
            url = download.presigned_get_object(row.bucket, disk["object"], expires=timedelta(days=7))
            original = next(v["pvc"] for v in row.restore_data["originals"] if v["volume_name"] == disk["volume_name"])
            dv = k8s.custom_api.create_namespaced_custom_object("cdi.kubevirt.io", "v1beta1", "default", "datavolumes", {
                "apiVersion": "cdi.kubevirt.io/v1beta1", "kind": "DataVolume",
                "metadata": {"name": target, "annotations": {"cdi.kubevirt.io/storage.bind.immediate.requested": "true",
                             "hosting.antigravity.io/s3-original-pvc": original},
                             "labels": {"hosting.antigravity.io/s3-restore": row.operation}},
                "spec": {"source": {"http": {"url": url}}, "pvc": disk["claim"]},
            })
        phase = dv.get("status", {}).get("phase")
        if phase == "Failed":
            raise RuntimeError(f"Импорт диска {target} завершился ошибкой")
        if phase != "Succeeded":
            return  # не переключаем ни один диск до готовности ВСЕХ
    row.restore_data = {**row.restore_data, "targets": targets}
    db.commit()
    current = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", row.vm_name)
    # Откатываем диски, не меняя текущие CPU/RAM/сеть и квоты пользователя.
    spec = copy.deepcopy(row.restore_data["vm_spec"])
    template = spec["template"]["spec"]
    by_name = {t["volume_name"]: t["pvc"] for t in targets}
    if set(by_name) != {d["volume_name"] for d in disk_volumes({"spec": spec})}:
        raise RuntimeError("Состав дисков изменился после копирования; восстановление остановлено без переключения")
    for vol in template["volumes"]:
        if vol["name"] in by_name:
            vol.pop("persistentVolumeClaim", None)
            vol["dataVolume"] = {"name": by_name[vol["name"]]}
    # Импортированные DV уже существуют; старые templates не пересоздаём.
    spec.pop("dataVolumeTemplates", None)
    spec.pop("running", None)
    spec["runStrategy"] = "Halted"
    k8s._patch_vm_json(row.vm_name, [
        {"op": "test", "path": "/metadata/resourceVersion", "value": current["metadata"]["resourceVersion"]},
        {"op": "test", "path": k8s._annotation_json_path(k8s.S3_OPERATION), "value": row.operation},
        {"op": "replace", "path": "/spec", "value": spec},
    ])
    row.restore_data = {**row.restore_data, "switched": True}
    # UI сетевых дисков должен ссылаться на новый PVC, а не на оригинал.
    from app.models.models import UserVolume
    for original in row.restore_data["originals"]:
        volume = db.query(UserVolume).filter(UserVolume.name == original["pvc"]).first()
        if volume:
            volume.name = by_name[original["volume_name"]]
    row.restore_state = "Finalizing"
    db.commit()
    # Оригиналы оставляем как страховку; не удаляем автоматически чужие или
    # разделяемые тома. Они перечислены в restore_data для оператора.
    _finish(db, k8s, row)


def process_archives(k8s):
    """Один проход фонового исполнителя. DB row lock исключает два worker."""
    with SessionLocal() as db:
        names = [r.name for r in db.query(VMArchive).filter(or_(VMArchive.status.in_(ACTIVE), VMArchive.operation.isnot(None))).all()]
    for name in names:
        from app.db import engine
        # Отдельное соединение удерживает session lock между commit прогресса.
        # SessionLocal возвращает соединение в пул при commit — lock на нём
        # держать нельзя: следующий тик мог бы попасть на другой connection.
        with engine.connect() as guard, SessionLocal() as db:
            from sqlalchemy import text
            locked = guard.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": "s3:" + name}).scalar()
            guard.commit()
            if not locked:
                continue
            try:
                row = db.query(VMArchive).filter(VMArchive.name == name).first()
                if not row:
                    continue
                if row.restore_state and row.restore_state != "Failed":
                    _restore(db, k8s, row)
                elif row.status == "Failed" or row.restore_state == "Failed":
                    _finish(db, k8s, row)
                else:
                    _capture(db, k8s, row)
            except Exception as error:
                logger.exception("Ошибка S3-операции %s", name)
                db.rollback()
                row = db.query(VMArchive).filter(VMArchive.name == name).first()
                if row:
                    if row.status == "Finalizing" or row.restore_state == "Finalizing":
                        # Диски уже сохранены/переключены. Сбой возврата питания
                        # или очистки экспортера должен повторять финализацию,
                        # а не удалять импортированные диски как неудавшиеся.
                        row.error = "Диски готовы; повторяется завершение операции S3. Подробности в логах worker"
                    else:
                        if not row.error:
                            row.error = "Не удалось завершить операцию S3; подробности в логах worker"
                        if row.restore_state:
                            row.restore_state = "Failed"
                        else:
                            row.status = "Failed"
                    db.commit()
            finally:
                guard.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": "s3:" + name})
                guard.commit()
