import os
import json
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.services.ssh_inspector import SSHInspector

router = APIRouter()
logger = logging.getLogger("app.api.external_servers")

# Путь для сохранения подключенных серверов
DATA_DIR = "/app/data"
SERVERS_FILE = os.path.join(DATA_DIR, "external_servers.json")

os.makedirs(DATA_DIR, exist_ok=True)

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

# Помощники для чтения/записи JSON
def read_servers() -> list:
    if not os.path.exists(SERVERS_FILE):
        return []
    try:
        with open(SERVERS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения файла серверов: {e}")
        return []

def write_servers(servers: list):
    try:
        with open(SERVERS_FILE, "w") as f:
            json.dump(servers, f, indent=2)
    except Exception as e:
        logger.error(f"Ошибка записи файла серверов: {e}")
        raise HTTPException(status_code=500, detail="Не удалось сохранить изменения на диск.")

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
def list_servers():
    """Получить список всех подключенных серверов с быстрой проверкой их онлайн-статуса"""
    servers = read_servers()
    if not servers:
        return []
        
    # Выполняем параллельную проверку доступности всех серверов
    # Ограничиваем таймаут, чтобы не вешать API
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(check_single_server_status, servers))
        
    return results

@router.post("", response_model=ExternalServerResponse, status_code=status.HTTP_201_CREATED)
def connect_server(server_in: ExternalServerCreate):
    """Подключить новый сервер (с предварительной проверкой SSH-связи)"""
    servers = read_servers()
    
    # Проверяем, нет ли уже сервера с таким IP
    if any(s["host"] == server_in.host for s in servers):
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

    # Создаем запись
    new_server = {
        "id": str(uuid.uuid4())[:8],
        "name": server_in.name,
        "host": server_in.host,
        "port": server_in.port,
        "username": server_in.username,
        "password": server_in.password
    }
    
    servers.append(new_server)
    write_servers(servers)
    
    return {
        "id": new_server["id"],
        "name": new_server["name"],
        "host": new_server["host"],
        "port": new_server["port"],
        "username": new_server["username"],
        "status": "Online"
    }

@router.delete("/{server_id}")
def disconnect_server(server_id: str):
    """Отключить сервер и удалить его реквизиты"""
    servers = read_servers()
    server_to_delete = None
    
    for s in servers:
        if s["id"] == server_id:
            server_to_delete = s
            break
            
    if not server_to_delete:
        raise HTTPException(
            status_code=404, 
            detail=f"Сервер с ID {server_id} не найден."
        )
        
    servers.remove(server_to_delete)
    write_servers(servers)
    return {"status": "disconnected", "id": server_id, "name": server_to_delete["name"]}

@router.get("/{server_id}/details")
def get_server_details(server_id: str):
    """Получить подробный живой отчет о состоянии удаленного сервера (Docker, Systemd, CPU/RAM)"""
    servers = read_servers()
    target_server = next((s for s in servers if s["id"] == server_id), None)
    
    if not target_server:
        raise HTTPException(
            status_code=404, 
            detail=f"Сервер с ID {server_id} не найден."
        )

    # Запускаем сбор детальных метрик
    inspector = SSHInspector(
        host=target_server["host"],
        port=target_server["port"],
        username=target_server["username"],
        password=target_server["password"]
    )
    
    metrics = inspector.inspect()
    # Возвращаем метаданные и собранные метрики
    return {
        "id": target_server["id"],
        "name": target_server["name"],
        "host": target_server["host"],
        "port": target_server["port"],
        "username": target_server["username"],
        **metrics
    }
