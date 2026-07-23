import asyncio
import logging
import json
import paramiko
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from app.core.k8s_client import K8sClient
from app.api.vms import resolve_vm_ip

router = APIRouter()
logger = logging.getLogger("app.ssh_terminal")

async def ws_to_ssh_loop(websocket: WebSocket, chan: paramiko.Channel):
    """Направляет ввод из вебсокета в интерактивный shell-канал SSH"""
    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break
                
            if "text" in data:
                text_data = data["text"]
                # Проверяем, не является ли это командой ресайза окна терминала
                try:
                    msg = json.loads(text_data)
                    if isinstance(msg, dict) and msg.get("type") == "resize":
                         cols = msg.get("cols", 80)
                         rows = msg.get("rows", 24)
                         chan.resize_pty(cols=cols, rows=rows)
                         continue
                except Exception:
                    pass
                # Обычный текст (ввод пользователя)
                await asyncio.to_thread(chan.send, text_data.encode('utf-8'))
            elif "bytes" in data:
                await asyncio.to_thread(chan.send, data["bytes"])
    except Exception as e:
        logger.debug(f"SSH WS input loop error: {e}")
    finally:
        try:
            chan.close()
        except Exception:
            pass

async def ssh_to_ws_loop(chan: paramiko.Channel, websocket: WebSocket):
    """Направляет вывод из shell-канала SSH в вебсокет"""
    try:
        while not chan.exit_status_ready():
            # Блокирующее чтение из SSH-канала выносим в рабочий поток через asyncio.to_thread
            data = await asyncio.to_thread(chan.recv, 4096)
            if not data:
                break
            await websocket.send_bytes(data)
    except Exception as e:
        logger.debug(f"SSH WS output loop error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

@router.websocket("/{name}")
async def ssh_terminal_proxy(
    websocket: WebSocket,
    name: str,
    token: str = Query(None)
):
    from app.core.auth import ADMIN_TOKEN, decode_access_token, secure_eq
    from app.models.models import User, VMTask
    from app.db import SessionLocal

    # 1. Авторизация
    is_authorized = False
    if token:
        if secure_eq(token, ADMIN_TOKEN):
            is_authorized = True
        else:
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                username = payload["sub"]
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.username == username).first()
                    if user:
                        if user.role == "admin":
                            is_authorized = True
                        else:
                            vm = db.query(VMTask).filter(VMTask.name == name).first()
                            if vm and vm.owner_id == user.id:
                                is_authorized = True
                finally:
                    db.close()

    if not is_authorized:
        logger.warning(f"Неавторизованное терминальное подключение к VM: {name}")
        await websocket.accept()
        await websocket.close(code=1008, reason="Unauthorized")
        return

    # Принимаем соединение
    await websocket.accept()
    logger.info(f"Запрос терминального SSH-сеанса для VM: {name}")

    # 2. Получаем параметры подключения по SSH
    try:
        k8s = K8sClient()
        vm = k8s.get_vm(name)
    except Exception as e:
        logger.error(f"VM {name} не найдена для SSH: {e}")
        await websocket.close(code=1011, reason=f"VM not found: {str(e)}")
        return

    if vm.get("status") != "Running":
        await websocket.close(code=1011, reason="VM is not running")
        return

    ips = vm.get("ips", [])
    external_ip = resolve_vm_ip(ips)
    if not external_ip:
        await websocket.close(code=1011, reason="VM has no IP address assigned")
        return

    credentials = vm.get("credentials", {})
    username = credentials.get("username", "root")
    password = credentials.get("password")

    if not password or password == "N/A":
        await websocket.close(code=1011, reason="SSH password not found in KubeVirt credentials")
        return

    # 3. Инициируем SSH-подключение
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info(f"Подключение по SSH к ВМ {name} по IP: {external_ip}...")
        ssh.connect(
            hostname=external_ip,
            port=22,
            username=username,
            password=password,
            timeout=10
        )
        # Открываем интерактивный shell
        chan = ssh.invoke_shell(term="xterm", width=80, height=24)
        logger.info(f"Успешно открыт SSH shell-канал для VM {name}")
    except Exception as e:
        logger.error(f"Ошибка подключения по SSH к VM {name} ({external_ip}): {e}")
        await websocket.close(code=1011, reason=f"SSH connection failed: {str(e)}")
        return

    # 4. Двунаправленный прокси-цикл
    try:
        await asyncio.gather(
            ws_to_ssh_loop(websocket, chan),
            ssh_to_ws_loop(chan, websocket),
            return_exceptions=True
        )
    finally:
        try:
            chan.close()
        except Exception:
            pass
        try:
            ssh.close()
        except Exception:
            pass
        logger.info(f"SSH терминальное соединение закрыто для VM: {name}")
