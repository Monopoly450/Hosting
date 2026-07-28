"""API маркетплейса: каталог приложений и деплой «в один клик»."""
import re
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, VMTask, AppDeployment
from app.core.auth import get_current_user
from app.services.marketplace import (
    get_catalog, get_app, resolve_env, build_marketplace_cloud_init,
    add_public_url, default_host,
)

router = APIRouter()
logger = logging.getLogger("app.api.marketplace")

NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class MarketplaceDeploy(BaseModel):
    app_id: str = Field(..., description="ID приложения из каталога")
    name: str = Field(..., description="Имя деплоя/ВМ (a-z, 0-9, дефис)")
    cpu_cores: int = Field(2, ge=1, le=16)
    memory_gb: int = Field(2, ge=1, le=64)
    disk_gb: int = Field(20, ge=10, le=500)
    env: dict = Field(default_factory=dict, description="Переопределения переменных окружения")


@router.get("/catalog")
def catalog(current_user: User = Depends(get_current_user)):
    """Список доступных приложений (без секретов и compose)."""
    return get_catalog()


@router.post("/deploy", status_code=status.HTTP_201_CREATED)
def deploy(req: MarketplaceDeploy, current_user: User = Depends(get_current_user)):
    app = get_app(req.app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Приложение не найдено в каталоге")
    if not NAME_RE.match(req.name):
        raise HTTPException(status_code=400, detail="Имя может содержать только a-z, 0-9 и дефис")

    from app.queue_client import publish_task
    from app.api.vms import generate_random_password, compute_static_ip

    db = SessionLocal()
    try:
        if db.query(AppDeployment).filter(AppDeployment.name == req.name).first():
            raise HTTPException(status_code=400, detail="Деплой с таким именем уже существует.")
        if db.query(VMTask).filter(VMTask.name == req.name).first():
            raise HTTPException(status_code=400, detail="ВМ с таким именем уже существует.")

        # Квоты студента (деплой создаёт выделенную ВМ). Проверка идёт под
        # блокировкой строки пользователя, чтобы параллельные запросы не смогли
        # проскочить лимит вдвоём.
        from app.core.quotas import enforce_quota
        from app.core.ratelimit import check_rate_limit
        check_rate_limit(current_user, "marketplace_deploy")
        enforce_quota(db, current_user, add_vms=1, add_vcpus=req.cpu_cores,
                      add_ram_gb=req.memory_gb, add_storage_gb=req.disk_gb)

        try:
            env = resolve_env(app, req.env)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        password = generate_random_password()
        app_port = app["app_port"]

        # Фаза 1: создаём ВМ, чтобы узнать её id (от него зависит внешний порт).
        vm = VMTask(
            name=req.name, os_type="ubuntu",
            cpu_cores=req.cpu_cores, memory_gb=req.memory_gb, disk_gb=req.disk_gb,
            owner_id=current_user.id, status="Pending",
        )
        db.add(vm)
        db.commit()
        db.refresh(vm)

        ext_port = 28000 + vm.id
        ports = [
            {"ext_port": 22000 + vm.id, "int_port": 22, "name": "SSH"},
            {"ext_port": ext_port, "int_port": app_port, "name": "APP"},
        ]
        vm.ports_config = json.dumps(ports)
        vm.static_ip = compute_static_ip(vm.id)

        # Фаза 2: внешний адрес известен — прокидываем его в приложение и только
        # теперь формируем cloud-init (воркер прочитает его при publish_task).
        env = add_public_url(env, default_host(), ext_port)
        vm.custom_user_data = build_marketplace_cloud_init(app, env, password)
        db.commit()

        dep = AppDeployment(
            name=req.name, repo_url=f"marketplace://{app['id']}", branch="-",
            stack="marketplace", app_port=app_port, run_command=None,
            vm_id=vm.id, vm_name=vm.name, owner_id=current_user.id, status="Deploying",
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)

        publish_task("vm_tasks", {"task_id": vm.id, "action": "create_vm"})

        # Секреты, которые сгенерировали для пользователя (показываем один раз)
        shown = {e["key"]: env[e["key"]] for e in app["env"] if e.get("secret")}
        return {
            "status": "deploying",
            "name": req.name,
            "app": app["name"],
            "app_port": app_port,
            "app_url": env["PUBLIC_URL"],
            "deployment_id": dep.id,
            "generated_secrets": shown,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
