import re
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, VMTask, AppDeployment
from app.core.auth import get_current_user
from app.core.netutils import host_for_links

router = APIRouter()
logger = logging.getLogger("app.api.deployments")

STACKS = {"compose", "dockerfile", "node", "python", "static", "custom"}

# Стеки, для которых показываем понятные подписи на фронте
STACK_LABELS = {
    "compose": "Docker Compose",
    "dockerfile": "Dockerfile",
    "node": "Node.js",
    "python": "Python",
    "static": "Статический сайт",
    "custom": "Своя команда",
    "marketplace": "Маркетплейс",
}


class DeploymentCreate(BaseModel):
    name: str = Field(..., pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", description="Имя деплоя (латиница, цифры, дефис)")
    repo_url: str = Field(..., description="URL Git-репозитория (https)")
    branch: str = Field("main", description="Ветка")
    stack: str = Field("compose", description="Тип стека")
    app_port: int = Field(3000, ge=1, le=65535, description="Порт приложения внутри ВМ")
    run_command: Optional[str] = Field(None, description="Команда запуска (для custom/переопределения)")
    cpu_cores: int = Field(2, ge=1, le=16)
    memory_gb: int = Field(2, ge=1, le=64)
    disk_gb: int = Field(20, ge=10, le=500)


class DeploymentResponse(BaseModel):
    id: int
    name: str
    repo_url: str
    branch: str
    stack: str
    stack_label: str
    app_port: int
    run_command: Optional[str] = None
    vm_name: Optional[str] = None
    status: str
    vm_status: Optional[str] = None
    ip: Optional[str] = None
    app_url: Optional[str] = None
    ssh_command: Optional[str] = None
    owner_username: str


_GIT_URL_RE = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+$")


def _is_vm_missing(exc: Exception) -> bool:
    """Отличает «ВМ не существует» от прочих сбоев обращения к Kubernetes.

    Нужно, чтобы не показывать пользователю сырой ответ API с заголовками:
    отсутствие ВМ и недоступность кластера — разные ситуации с разными
    действиями со стороны пользователя.
    """
    status = getattr(exc, "status", None)
    if status == 404:
        return True
    text = str(exc).lower()
    return "not found" in text or '"code":404' in text or "(404)" in text


def _validate_repo(url: str):
    if not _GIT_URL_RE.match(url) or " " in url:
        raise HTTPException(status_code=400, detail="Укажите корректный https-URL репозитория (например, https://github.com/user/repo).")


def build_deploy_cloud_init(name: str, repo_url: str, branch: str, stack: str,
                            app_port: int, run_command: Optional[str], password: str) -> str:
    """Собирает полный #cloud-config: базовая настройка (пароль, guest-agent)
    + клонирование репозитория и запуск приложения по выбранному стеку.

    Сеть здесь не настраивается: её задаёт networkData в самом манифесте ВМ
    (см. build_network_data в app.services.cloudinit), одинаково для обычных
    ВМ, маркетплейса и деплоя из GitHub.
    """
    default_user = "ubuntu"
    app_dir = "/opt/app"
    rc = (run_command or "").strip()

    # Пакеты и шаги запуска под каждый стек
    if stack == "compose":
        pkgs = ["git", "docker.io", "docker-compose-v2"]
        deploy_steps = [
            f"cd {app_dir} && (docker compose up -d --build || docker-compose up -d --build) || true",
        ]
    elif stack == "dockerfile":
        pkgs = ["git", "docker.io"]
        deploy_steps = [
            f"cd {app_dir} && docker build -t {name}-app . || true",
            f"docker rm -f {name}-app 2>/dev/null || true",
            f"docker run -d --restart always --name {name}-app -p {app_port}:{app_port} {name}-app || true",
        ]
    elif stack == "node":
        pkgs = ["git", "nodejs", "npm"]
        start_cmd = rc or "npm start"
        deploy_steps = [
            f"cd {app_dir} && (npm ci || npm install) || true",
            _systemd_service(name, app_dir, start_cmd, app_port),
        ]
    elif stack == "python":
        pkgs = ["git", "python3", "python3-pip", "python3-venv"]
        start_cmd = rc or "python3 app.py"
        deploy_steps = [
            f"cd {app_dir} && python3 -m venv .venv && . .venv/bin/activate && (pip install -r requirements.txt || true)",
            _systemd_service(name, app_dir, f"/opt/app/.venv/bin/{start_cmd}" if start_cmd.startswith(('python', 'gunicorn', 'uvicorn', 'flask')) else start_cmd, app_port),
        ]
    elif stack == "static":
        pkgs = ["git", "nginx"]
        deploy_steps = [
            f"rm -rf /var/www/html && ln -s {app_dir} /var/www/html || true",
            f"sed -i 's/listen 80/listen {app_port}/' /etc/nginx/sites-enabled/default 2>/dev/null || true",
            "systemctl restart nginx || true",
        ]
    else:  # custom
        pkgs = ["git", "docker.io"]
        deploy_steps = [f"cd {app_dir} && ({rc or 'echo no run command'}) || true"]

    packages_yaml = "\n".join(f"  - {p}" for p in pkgs)
    from app.services.cloudinit import (GUEST_AGENT_RETRY_RUNCMD, WAIT_NETWORK_RUNCMD,
                                        yaml_runcmd_lines)

    # URL репозитория и имя ветки тоже приходят от пользователя.
    clone_yaml = yaml_runcmd_lines([
        f"git clone --depth 1 --branch {branch} {repo_url} {app_dir} "
        f"|| git clone --depth 1 {repo_url} {app_dir}"
    ])

    # Шаги деплоя экранируем: сюда попадает run_command, который задаёт сам
    # пользователь. Двоеточие с пробелом в нём (вполне обычное дело —
    # `echo 'старт: ok' && npm start`) превращало элемент runcmd в словарь,
    # и деплой молча не выполнялся целиком. См. yaml_runcmd_lines.
    deploy_yaml = yaml_runcmd_lines(deploy_steps)

    return f"""#cloud-config
ssh_pwauth: True
disable_root: false
chpasswd:
  list: |
    root:{password}
    {default_user}:{password}
  expire: False
users:
  - default
packages:
{packages_yaml}
runcmd:
  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
  - sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config.d/*.conf || true
  - echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config || true
  - systemctl restart ssh || systemctl restart sshd || true
{WAIT_NETWORK_RUNCMD}
  - apt-get update || true
  - systemctl enable --now docker 2>/dev/null || true
  - usermod -aG docker {default_user} 2>/dev/null || true
{clone_yaml}
{deploy_yaml}
{GUEST_AGENT_RETRY_RUNCMD}
"""


def _systemd_service(name: str, workdir: str, exec_cmd: str, app_port: int) -> str:
    """Однострочный runcmd, который создаёт и запускает systemd-сервис приложения."""
    unit = (
        "[Unit]\\nDescription=App {n}\\nAfter=network.target\\n\\n"
        "[Service]\\nWorkingDirectory={wd}\\nEnvironment=PORT={p}\\n"
        "ExecStart=/bin/bash -lc '{cmd}'\\nRestart=always\\nUser=root\\n\\n"
        "[Install]\\nWantedBy=multi-user.target"
    ).format(n=name, wd=workdir, p=app_port, cmd=exec_cmd.replace("'", "'\\''"))
    return (
        f"printf '{unit}' > /etc/systemd/system/{name}-app.service && "
        f"systemctl daemon-reload && systemctl enable --now {name}-app.service || true"
    )


def _get_host() -> str:
    from app.core.netutils import detect_host_ip
    return detect_host_ip()


def _enrich(dep: AppDeployment, owner_name: str, request=None) -> DeploymentResponse:
    """Дополняет запись деплоя живым статусом ВМ, IP и внешним URL.

    request нужен, чтобы ссылки указывали на тот адрес, по которому открыта
    панель (см. host_for_links)."""
    vm_status = None
    ip = None
    app_url = None
    ssh_command = None
    ext_app_port = None
    if dep.vm_name:
        try:
            from app.core.k8s_client import K8sClient
            from app.core.netutils import pick_external_ip
            vm = K8sClient().get_vm(dep.vm_name)
            vm_status = vm.get("status")
            ips = vm.get("ips", [])
            ip = pick_external_ip(ips) if ips else None
            ssh_port = vm.get("ssh_port")
            host = host_for_links(request)
            if ssh_port:
                ssh_command = f"ssh ubuntu@{host} -p {ssh_port}"
            # Внешний порт приложения хранится в ports_config ВМ (int_port == app_port)
            if dep.vm_id:
                db2 = SessionLocal()
                try:
                    vmt = db2.query(VMTask).filter(VMTask.id == dep.vm_id).first()
                    if vmt and vmt.ports_config:
                        for p in json.loads(vmt.ports_config):
                            if p.get("int_port") == dep.app_port:
                                ext_app_port = p.get("ext_port")
                finally:
                    db2.close()
            if ext_app_port:
                app_url = f"http://{host}:{ext_app_port}"
        except Exception as e:
            logger.warning(f"enrich deployment {dep.name}: {e}")

    status_val = dep.status
    if vm_status == "Running" and status_val == "Deploying":
        status_val = "Running"
    elif vm_status == "Error":
        status_val = "Error"

    return DeploymentResponse(
        id=dep.id, name=dep.name, repo_url=dep.repo_url, branch=dep.branch,
        stack=dep.stack, stack_label=STACK_LABELS.get(dep.stack, dep.stack),
        app_port=dep.app_port, run_command=dep.run_command, vm_name=dep.vm_name,
        status=status_val, vm_status=vm_status, ip=ip, app_url=app_url,
        ssh_command=ssh_command, owner_username=owner_name,
    )


@router.post("", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
def create_deployment(req: DeploymentCreate, request: Request, current_user: User = Depends(get_current_user)):
    if req.stack not in STACKS:
        raise HTTPException(status_code=400, detail="Неизвестный тип стека.")
    if req.stack == "custom" and not (req.run_command and req.run_command.strip()):
        raise HTTPException(status_code=400, detail="Для стека «Своя команда» укажите команду запуска.")
    _validate_repo(req.repo_url)

    from app.queue_client import publish_task
    from app.api.vms import generate_random_password

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
        from app.core.capacity import lock_host_capacity, ensure_host_capacity
        check_rate_limit(current_user, "create_deployment")
        enforce_quota(db, current_user, add_vms=1, add_vcpus=req.cpu_cores,
                      add_ram_gb=req.memory_gb, add_storage_gb=req.disk_gb)
        # См. пояснение в marketplace.py: квота — про пользователя, а это про
        # то, что ресурсы хоста действительно есть.
        lock_host_capacity(db)
        ensure_host_capacity(db, cpu_cores=req.cpu_cores,
                             memory_gb=req.memory_gb, disk_gb=req.disk_gb)

        password = generate_random_password()

        # Фаза 1: создаём ВМ, чтобы узнать её id — от него зависят внешний
        # порт и статический IP на мосту br-vms (тот же порядок, что и в
        # маркетплейсе: cloud-init нельзя собрать раньше, ему нужен static_ip).
        vm = VMTask(
            name=req.name, os_type="ubuntu",
            cpu_cores=req.cpu_cores, memory_gb=req.memory_gb, disk_gb=req.disk_gb,
            owner_id=current_user.id, status="Pending",
        )
        db.add(vm)
        db.commit()
        db.refresh(vm)

        # Пробрасываем SSH и порт приложения (стабильно, по ID ВМ)
        ports = [
            {"ext_port": 22000 + vm.id, "int_port": 22, "name": "SSH"},
            {"ext_port": 28000 + vm.id, "int_port": req.app_port, "name": "APP"},
        ]
        vm.ports_config = json.dumps(ports)
        from app.api.vms import compute_static_ip
        # Статический адрес на мосту применит networkData в манифесте — его
        # соберёт воркер по этому же static_ip (см. generate_linux_manifest).
        vm.static_ip = compute_static_ip(vm.id)

        cloud_init = build_deploy_cloud_init(
            req.name, req.repo_url, req.branch, req.stack, req.app_port, req.run_command, password
        )
        vm.custom_user_data = cloud_init
        # Пароль уже вписан в cloud_init — сохраняем его же, иначе воркер
        # положит в Secret другой, и панель не сможет зайти в ВМ по SSH.
        from app.core.crypto import encrypt_secret
        vm.vm_password = encrypt_secret(password)
        db.commit()

        dep = AppDeployment(
            name=req.name, repo_url=req.repo_url, branch=req.branch, stack=req.stack,
            app_port=req.app_port, run_command=req.run_command,
            vm_id=vm.id, vm_name=vm.name, owner_id=current_user.id, status="Deploying",
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)

        from app.queue_client import publish_task_or_fail_task
        if not publish_task_or_fail_task("vm_tasks", {"task_id": vm.id, "action": "create_vm"}, db, vm):
            raise HTTPException(status_code=503, detail="Сервис очередей недоступен, попробуйте позже.")
        return _enrich(dep, current_user.username, request)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("", response_model=List[DeploymentResponse])
def list_deployments(request: Request, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            deps = db.query(AppDeployment).all()
        else:
            deps = db.query(AppDeployment).filter(AppDeployment.owner_id == current_user.id).all()
        res = []
        for d in deps:
            owner = db.query(User).filter(User.id == d.owner_id).first()
            res.append(_enrich(d, owner.username if owner else "—", request))
        return res
    finally:
        db.close()


@router.delete("/{dep_id}", status_code=status.HTTP_200_OK)
def delete_deployment(dep_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        dep = db.query(AppDeployment).filter(AppDeployment.id == dep_id).first()
        if not dep:
            raise HTTPException(status_code=404, detail="Деплой не найден.")
        if current_user.role != "admin" and dep.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещён.")

        # Удаляем выделенную ВМ (через очередь) и запись VMTask
        vm_id_to_delete = dep.vm_id
        if dep.vm_name:
            try:
                from app.queue_client import publish_task
                if dep.vm_id:
                    publish_task("vm_tasks", {"task_id": dep.vm_id, "action": "delete_vm"})
            except Exception as e:
                logger.error(f"Failed to queue VM delete for deployment {dep.name}: {e}")

        # Сначала удаляем сам деплой
        db.delete(dep)
        db.flush()

        # Затем безопасно удаляем запись ВМ
        if vm_id_to_delete:
            vmt = db.query(VMTask).filter(VMTask.id == vm_id_to_delete).first()
            if vmt:
                db.delete(vmt)

        db.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{dep_id}/logs")
def get_deployment_logs(dep_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        dep = db.query(AppDeployment).filter(AppDeployment.id == dep_id).first()
        if not dep:
            raise HTTPException(status_code=404, detail="Деплой не найден.")
        if current_user.role != "admin" and dep.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещён.")

        if not dep.vm_name:
            return {"logs": "Виртуальная машина еще не создана."}

        # Получаем данные ВМ из KubeVirt
        from app.core.k8s_client import K8sClient
        from app.core.netutils import pick_external_ip
        try:
            k8s = K8sClient()
            vm = k8s.get_vm(dep.vm_name)
        except Exception as e:
            # Частый случай: ВМ так и не создалась (сбой воркера или очереди).
            # Показывать сырой ответ Kubernetes с заголовками бессмысленно —
            # объясняем, что произошло и что делать.
            if _is_vm_missing(e):
                return {"logs": (
                    f"Виртуальная машина «{dep.vm_name}» не найдена в кластере — "
                    "скорее всего, она не была создана из-за сбоя при развёртывании.\n\n"
                    "Логи собираются внутри ВМ, поэтому показать их нечего.\n"
                    "Удалите этот деплой и создайте приложение заново."
                )}
            logger.warning(f"Логи деплоя {dep.name}: не удалось получить ВМ: {e}")
            return {"logs": "Не удалось получить информацию о виртуальной машине. "
                            "Попробуйте позже или проверьте состояние кластера."}

        if vm.get("status") != "Running":
            return {"logs": f"Виртуальная машина не запущена. Текущий статус: {vm.get('status', 'Unknown')}"}

        # Получаем IP
        ips = vm.get("ips", [])
        ip = pick_external_ip(ips)
        if not ip:
            return {"logs": "У виртуальной машины еще нет IP адреса. Ожидайте запуска."}

        # Получаем пароль из секрета
        credentials = vm.get("credentials", {})
        username = credentials.get("username", "ubuntu")
        password = credentials.get("password")
        if not password or password == "N/A":
            return {"logs": "Не найдены учетные данные для подключения по SSH."}

        # Подключаемся по SSH и читаем логи
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(hostname=ip, port=22, username=username, password=password, timeout=5)
        except Exception as e:
            return {"logs": f"Не удалось подключиться к ВМ по SSH для чтения логов: {e}\n(Возможно, система еще запускается и настраивает сетевые интерфейсы. Подождите 1-2 минуты.)"}

        try:
            # 1. Читаем логи сборки (cloud-init)
            stdin, stdout, stderr = ssh.exec_command("cat /var/log/cloud-init-output.log", timeout=5)
            build_logs = stdout.read().decode("utf-8", errors="replace")
            
            # 2. Читаем логи самого приложения в зависимости от стека
            app_logs = ""
            if dep.stack == "compose":
                _, out, _ = ssh.exec_command("cd /opt/app && (docker compose logs --tail=100 || docker-compose logs --tail=100)", timeout=5)
                app_logs = out.read().decode("utf-8", errors="replace")
            elif dep.stack == "dockerfile":
                _, out, _ = ssh.exec_command(f"docker logs --tail=100 {dep.name}-app", timeout=5)
                app_logs = out.read().decode("utf-8", errors="replace")
            elif dep.stack in ("node", "python", "custom"):
                _, out, _ = ssh.exec_command(f"journalctl -u {dep.name}-app -n 100 --no-pager", timeout=5)
                app_logs = out.read().decode("utf-8", errors="replace")
            elif dep.stack == "static":
                _, out, _ = ssh.exec_command("tail -n 100 /var/log/nginx/error.log", timeout=5)
                app_logs = out.read().decode("utf-8", errors="replace")

            full_logs = "=== ЛОГИ СБОРКИ И НАСТРОЙКИ (CLOUD-INIT) ===\n"
            full_logs += build_logs or "Логи сборки пусты или еще не записаны.\n"
            
            if app_logs.strip():
                full_logs += "\n\n=== ЛОГИ ЗАПУСКА ПРИЛОЖЕНИЯ ===\n"
                full_logs += app_logs

            return {"logs": full_logs}
        except Exception as e:
            return {"logs": f"Ошибка чтения логов из ВМ: {e}"}
        finally:
            ssh.close()
    finally:
        db.close()


@router.post("/{dep_id}/redeploy")
def redeploy_app(dep_id: int, current_user: User = Depends(get_current_user)):
    import datetime
    db = SessionLocal()
    try:
        dep = db.query(AppDeployment).filter(AppDeployment.id == dep_id).first()
        if not dep:
            raise HTTPException(status_code=404, detail="Деплой не найден.")
        if current_user.role != "admin" and dep.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещён.")

        # У приложения из маркетплейса нет репозитория: branch хранит прочерк, а
        # каталога /opt/app не существует — команды ниже сделали бы
        # «git reset --hard origin/-» и вернули невнятную ошибку git.
        if dep.stack == "marketplace":
            raise HTTPException(
                status_code=400,
                detail="Приложение установлено из маркетплейса, а не из репозитория: "
                       "передеплой через git к нему не применяется.",
            )

        if not dep.vm_name:
            raise HTTPException(status_code=400, detail="Виртуальная машина еще не создана.")

        from app.core.k8s_client import K8sClient
        from app.core.netutils import pick_external_ip
        try:
            k8s = K8sClient()
            vm = k8s.get_vm(dep.vm_name)
        except Exception as e:
            if _is_vm_missing(e):
                raise HTTPException(
                    status_code=404,
                    detail=f"Виртуальная машина «{dep.vm_name}» не найдена в кластере. "
                           "Передеплой невозможен — удалите деплой и создайте заново."
                )
            logger.warning(f"Передеплой {dep.name}: не удалось получить ВМ: {e}")
            raise HTTPException(status_code=502, detail="Не удалось получить информацию о виртуальной машине.")

        if vm.get("status") != "Running":
            raise HTTPException(status_code=400, detail="Виртуальная машина должна быть запущена для передеплоя.")

        ips = vm.get("ips", [])
        ip = pick_external_ip(ips)
        if not ip:
            raise HTTPException(status_code=400, detail="У виртуалки нет IP адреса.")

        credentials = vm.get("credentials", {})
        username = credentials.get("username", "ubuntu")
        password = credentials.get("password")
        if not password or password == "N/A":
            raise HTTPException(status_code=400, detail="Не найден пароль SSH.")

        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(hostname=ip, port=22, username=username, password=password, timeout=10)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка подключения по SSH: {e}")

        try:
            app_dir = "/opt/app"
            commands = [
                f"cd {app_dir} && git fetch --all && git reset --hard origin/{dep.branch}"
            ]
            if dep.stack == "compose":
                commands.append(f"cd {app_dir} && (docker compose up -d --build || docker-compose up -d --build)")
            elif dep.stack == "dockerfile":
                commands.extend([
                    f"cd {app_dir} && docker build -t {dep.name}-app .",
                    f"docker rm -f {dep.name}-app 2>/dev/null || true",
                    f"docker run -d --restart always --name {dep.name}-app -p {dep.app_port}:{dep.app_port} {dep.name}-app"
                ])
            elif dep.stack == "node":
                commands.extend([
                    f"cd {app_dir} && (npm ci || npm install)",
                    f"systemctl restart {dep.name}-app.service"
                ])
            elif dep.stack == "python":
                commands.extend([
                    f"cd {app_dir} && . .venv/bin/activate && (pip install -r requirements.txt || true)",
                    f"systemctl restart {dep.name}-app.service"
                ])
            elif dep.stack == "static":
                commands.append("systemctl restart nginx")
            else:  # custom
                rc = (dep.run_command or "").strip()
                commands.append(f"cd {app_dir} && ({rc or 'echo no run command'})")

            # Выполняем команды последовательно
            output = ""
            for cmd in commands:
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                output += f"$ {cmd}\n{out}"
                if err:
                    output += f"[ERR]\n{err}"
            
            # Пишем лог передеплоя в файл
            log_header = f"\n\n=== RE-DEPLOY BY USER AT {datetime.datetime.utcnow().isoformat()} ===\n"
            sanitized_output = output.replace("'", "'\\''")
            ssh.exec_command(f"echo '{log_header}{sanitized_output}' >> /var/log/cloud-init-output.log")

            dep.status = "Running"
            db.commit()
            return {"status": "success", "output": output}
        except Exception as e:
            dep.status = "Error"
            db.commit()
            raise HTTPException(status_code=500, detail=f"Ошибка выполнения команд передеплоя: {e}")
        finally:
            ssh.close()
    finally:
        db.close()
