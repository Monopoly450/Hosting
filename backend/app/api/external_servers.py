import os
import uuid
import logging
import paramiko
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
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

class ExternalServerResponse(BaseModel):
    id: str
    name: str
    host: str
    port: int
    username: str
    status: str = "Unknown"

# Функция проверки статуса одного сервера (для многопоточного обхода)
def check_single_server_status(server: dict) -> dict:
    inspector = SSHInspector(
        host=server["host"],
        port=server["port"],
        username=server["username"],
        password=server["password"]
    )
    is_online = inspector.test_connection()
    return {
        "id": server["id"],
        "name": server["name"],
        "host": server["host"],
        "port": server["port"],
        "username": server["username"],
        "status": "Online" if is_online else "Offline"
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
        "password": s.password
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

    # Проверяем подключение
    logger.info(f"Проверка SSH соединения перед добавлением сервера: {server_in.host}...")
    inspector = SSHInspector(
        host=server_in.host,
        port=server_in.port,
        username=server_in.username,
        password=server_in.password
    )
    if not inspector.test_connection():
        raise HTTPException(
            status_code=400,
            detail="Не удалось подключиться к серверу по SSH. Проверьте IP, порт, имя пользователя и пароль."
        )

    # Создаем запись в БД
    new_id = str(uuid.uuid4())[:8]
    new_server = ExternalServer(
        id=new_id,
        name=server_in.name,
        host=server_in.host,
        port=server_in.port,
        username=server_in.username,
        password=server_in.password
    )
    
    db.add(new_server)
    await db.commit()
    
    return {
        "id": new_id,
        "name": server_in.name,
        "host": server_in.host,
        "port": server_in.port,
        "username": server_in.username,
        "status": "Online"
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

    # Запускаем сбор детальных метрик
    inspector = SSHInspector(
        host=server.host,
        port=server.port,
        username=server.username,
        password=server.password
    )
    
    metrics = inspector.inspect()
    return {
        "id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "username": server.username,
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

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=server.host,
            port=server.port,
            username=server.username,
            password=server.password,
            timeout=15
        )
        
        # Определяем команду с переходом в рабочую директорию
        cwd_dir = req.cwd if req.cwd else "~"
        full_command = f"cd {cwd_dir} && {req.command} ; echo \"__CWD__\" ; pwd"
        
        stdin, stdout, stderr = ssh.exec_command(full_command, timeout=15)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        ssh.close()
        
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
