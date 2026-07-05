import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.crypto import encrypt_secret, decrypt_secret
from app.models.models import ExternalServer
from app.services.ssh_inspector import SSHInspector

router = APIRouter()
logger = logging.getLogger("app.api.external_servers")

# Модели данных
class ExternalServerCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Имя/Алиас сервера")
    host: str = Field(..., description="IP-адрес или Hostname")
    port: int = Field(22, ge=1, le=65535, description="SSH Порт")
    username: str = Field("root", description="Имя пользователя")
    password: str = Field(..., min_length=1, description="Пароль пользователя")
    # Опциональный бастион (jump host)
    bastion_host: Optional[str] = Field(None, description="Хост бастиона (jump host)")
    bastion_port: int = Field(22, ge=1, le=65535, description="SSH порт бастиона")
    bastion_username: Optional[str] = Field(None, description="Пользователь бастиона")
    bastion_password: Optional[str] = Field(None, description="Пароль бастиона")

class ExternalServerResponse(BaseModel):
    id: str
    name: str
    host: str
    port: int
    username: str
    status: str = "Unknown"
    use_bastion: bool = False
    bastion_host: Optional[str] = None

def _inspector_from(server: dict) -> SSHInspector:
    return SSHInspector(
        host=server["host"],
        port=server["port"],
        username=server["username"],
        password=server["password"],
        bastion_host=server.get("bastion_host"),
        bastion_port=server.get("bastion_port") or 22,
        bastion_username=server.get("bastion_username"),
        bastion_password=server.get("bastion_password"),
    )

# Функция проверки статуса одного сервера (для многопоточного обхода)
def check_single_server_status(server: dict) -> dict:
    inspector = _inspector_from(server)
    is_online = inspector.test_connection()
    return {
        "id": server["id"],
        "name": server["name"],
        "host": server["host"],
        "port": server["port"],
        "username": server["username"],
        "status": "Online" if is_online else "Offline",
        "use_bastion": inspector.uses_bastion,
        "bastion_host": server.get("bastion_host"),
    }


@router.get("", response_model=List[ExternalServerResponse])
async def list_servers(db: AsyncSession = Depends(get_db)):
    """Получить список всех подключенных серверов с быстрой проверкой их онлайн-статуса"""
    res = await db.execute(select(ExternalServer))
    servers = res.scalars().all()

    servers_list = [{
        "id": s.id,
        "name": s.name,
        "host": s.host,
        "port": s.port,
        "username": s.username,
        "password": decrypt_secret(s.password),
        "bastion_host": s.bastion_host,
        "bastion_port": s.bastion_port,
        "bastion_username": s.bastion_username,
        "bastion_password": decrypt_secret(s.bastion_password) if s.bastion_password else None,
    } for s in servers]

    if not servers_list:
        return []

    # Выполняем параллельную проверку доступности всех серверов
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(check_single_server_status, servers_list))

    return results

@router.post("", response_model=ExternalServerResponse, status_code=status.HTTP_201_CREATED)
async def connect_server(server_in: ExternalServerCreate, db: AsyncSession = Depends(get_db)):
    """Подключить новый сервер (с предварительной проверкой SSH-связи)"""
    res = await db.execute(select(ExternalServer).filter_by(host=server_in.host))
    if res.scalars().first():
        raise HTTPException(
            status_code=400, 
            detail=f"Сервер с хостом {server_in.host} уже подключен."
        )

    use_bastion = bool(server_in.bastion_host and server_in.bastion_username)
    if server_in.bastion_host and not (server_in.bastion_username and server_in.bastion_password):
        raise HTTPException(
            status_code=400,
            detail="Для бастиона укажите и пользователя, и пароль."
        )

    # Проверяем подключение (через бастион, если задан)
    via = f" через бастион {server_in.bastion_host}" if use_bastion else ""
    logger.info(f"Проверка SSH соединения перед добавлением сервера: {server_in.host}{via}...")
    inspector = SSHInspector(
        host=server_in.host,
        port=server_in.port,
        username=server_in.username,
        password=server_in.password,
        bastion_host=server_in.bastion_host,
        bastion_port=server_in.bastion_port,
        bastion_username=server_in.bastion_username,
        bastion_password=server_in.bastion_password,
    )
    if not inspector.test_connection():
        detail = "Не удалось подключиться к серверу по SSH. Проверьте IP, порт, имя пользователя и пароль."
        if use_bastion:
            detail += " Также проверьте доступность и учётные данные бастиона."
        raise HTTPException(status_code=400, detail=detail)

    # Создаем запись в БД
    new_id = str(uuid.uuid4())[:8]
    new_server = ExternalServer(
        id=new_id,
        name=server_in.name,
        host=server_in.host,
        port=server_in.port,
        username=server_in.username,
        password=encrypt_secret(server_in.password),
        bastion_host=server_in.bastion_host,
        bastion_port=server_in.bastion_port,
        bastion_username=server_in.bastion_username,
        bastion_password=encrypt_secret(server_in.bastion_password) if server_in.bastion_password else None,
    )

    db.add(new_server)
    await db.commit()

    return {
        "id": new_id,
        "name": server_in.name,
        "host": server_in.host,
        "port": server_in.port,
        "username": server_in.username,
        "status": "Online",
        "use_bastion": use_bastion,
        "bastion_host": server_in.bastion_host,
    }

@router.delete("/{server_id}")
async def disconnect_server(server_id: str, db: AsyncSession = Depends(get_db)):
    """Отключить сервер и удалить его реквизиты"""
    res = await db.execute(select(ExternalServer).filter_by(id=server_id))
    server = res.scalars().first()
    
    if not server:
        raise HTTPException(
            status_code=404, 
            detail=f"Сервер с ID {server_id} не найден."
        )
        
    await db.delete(server)
    await db.commit()
    return {"status": "disconnected", "id": server_id, "name": server.name}

@router.get("/{server_id}/details")
async def get_server_details(server_id: str, db: AsyncSession = Depends(get_db)):
    """Получить подробный живой отчет о состоянии удаленного сервера (Docker, Systemd, CPU/RAM)"""
    res = await db.execute(select(ExternalServer).filter_by(id=server_id))
    server = res.scalars().first()
    
    if not server:
        raise HTTPException(
            status_code=404, 
            detail=f"Сервер с ID {server_id} не найден."
        )

    # Запускаем сбор детальных метрик (через бастион, если задан)
    inspector = SSHInspector(
        host=server.host,
        port=server.port,
        username=server.username,
        password=decrypt_secret(server.password),
        bastion_host=server.bastion_host,
        bastion_port=server.bastion_port or 22,
        bastion_username=server.bastion_username,
        bastion_password=decrypt_secret(server.bastion_password) if server.bastion_password else None,
    )

    metrics = inspector.inspect()
    return {
        "id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "username": server.username,
        "use_bastion": inspector.uses_bastion,
        "bastion_host": server.bastion_host,
        **metrics
    }


class CommandExecuteRequest(BaseModel):
    command: str = Field(..., description="Команда для выполнения на удаленном сервере")
    cwd: Optional[str] = Field(None, description="Текущая рабочая директория")


@router.post("/{server_id}/execute")
async def execute_ssh_command(server_id: str, req: CommandExecuteRequest, db: AsyncSession = Depends(get_db)):
    """Выполнить произвольную команду на внешнем сервере через SSH"""
    res = await db.execute(select(ExternalServer).filter_by(id=server_id))
    server = res.scalars().first()
    
    if not server:
        raise HTTPException(
            status_code=404, 
            detail=f"Сервер с ID {server_id} не найден."
        )

    inspector = SSHInspector(
        host=server.host,
        port=server.port,
        username=server.username,
        password=decrypt_secret(server.password),
        bastion_host=server.bastion_host,
        bastion_port=server.bastion_port or 22,
        bastion_username=server.bastion_username,
        bastion_password=decrypt_secret(server.bastion_password) if server.bastion_password else None,
    )
    ssh = jump = None
    try:
        ssh, jump = inspector.open(timeout=15)

        # Определяем команду с переходом в рабочую директорию
        cwd_dir = req.cwd if req.cwd else "~"
        full_command = f"cd {cwd_dir} && {req.command} ; echo \"__CWD__\" ; pwd"

        stdin, stdout, stderr = ssh.exec_command(full_command, timeout=15)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')

        # Выделяем реальный вывод команды и новый CWD
        new_cwd = cwd_dir
        actual_out = out
        if "__CWD__" in out:
            parts = out.split("__CWD__")
            actual_out = parts[0].rstrip("\r\n").rstrip("\n")
            new_cwd = parts[1].strip()

        return {
            "exit_status": exit_status,
            "stdout": actual_out,
            "stderr": err,
            "cwd": new_cwd
        }
    except Exception as e:
        logger.error(f"Ошибка выполнения удаленной команды на {server.host}: {e}")
        return {
            "exit_status": -1,
            "stdout": "",
            "stderr": f"Не удалось выполнить команду по SSH: {str(e)}",
            "cwd": req.cwd if req.cwd else "~"
        }
    finally:
        SSHInspector.close_clients(ssh, jump)
