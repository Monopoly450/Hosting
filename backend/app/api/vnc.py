import asyncio
import ssl
import logging
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.k8s_client import K8sClient

router = APIRouter()
logger = logging.getLogger("app.vnc")

async def forward(source, destination):
    """Направляет сообщения из source в destination"""
    try:
        async for message in source:
            await destination.send(message)
    except Exception as e:
        logger.debug(f"Исключение при пересылке данных VNC: {e}")

@router.websocket("/{name}")
async def vnc_proxy(websocket: WebSocket, name: str, namespace: str = "default"):
    # Принимаем WebSocket-соединение от браузера с указанием бинарного подпротокола
    await websocket.accept(subprotocol="binary")
    logger.info(f"Запрос VNC WebSocket для виртуалки: {name}")
    
    try:
        k8s = K8sClient()
        info = k8s.get_api_server_info()
        conf = k8s.api_client.configuration
        
        # Преобразуем https:// в wss://
        host_clean = info["host"].replace("https://", "wss://").replace("http://", "ws://")
        wss_url = f"{host_clean}/apis/subresources.kubevirt.io/v1/namespaces/{namespace}/virtualmachineinstances/{name}/vnc"
        
        # Настройка SSL
        ssl_context = ssl.create_default_context()
        if info["verify_ssl"] and info["ssl_ca_cert"]:
            ssl_context.load_verify_locations(info["ssl_ca_cert"])
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        # Извлечение авторизационных токенов
        headers = {}
        if conf.api_key and "authorization" in conf.api_key:
            headers["Authorization"] = conf.api_key["authorization"]
        elif hasattr(conf, 'api_key_prefix') and conf.api_key_prefix.get("authorization"):
            headers["Authorization"] = f"{conf.api_key_prefix['authorization']} {conf.api_key.get('authorization')}"
        elif conf.api_key.get("BearerToken"):
             headers["Authorization"] = f"Bearer {conf.api_key.get('BearerToken')}"
        elif hasattr(conf, 'token') and conf.token:
            headers["Authorization"] = f"Bearer {conf.token}"
            
        # Поддержка авторизации по клиентским сертификатам (дефолт для K3s)
        if conf.cert_file and conf.key_file:
            ssl_context.load_cert_chain(certfile=conf.cert_file, keyfile=conf.key_file)
            logger.info("Используем клиентские SSL-сертификаты из kubeconfig для VNC")
            
        logger.info(f"Подключение к KubeVirt VNC по адресу: {wss_url}")
        
        # Подключаемся к API KubeVirt
        async with websockets.connect(
            wss_url, 
            ssl=ssl_context, 
            extra_headers=headers, 
            subprotocols=["binary"]
        ) as target_ws:
            logger.info(f"Успешное соединение с KubeVirt VNC для VM {name}")
            
            # Обертка для FastAPI WebSocket, чтобы привести его к интерфейсу websockets
            class FastAPIWSWrapper:
                def __init__(self, ws: WebSocket):
                    self.ws = ws
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    try:
                        data = await self.ws.receive()
                        if data.get("type") == "websocket.disconnect":
                            raise StopAsyncIteration
                        if "bytes" in data:
                            return data["bytes"]
                        elif "text" in data:
                            return data["text"].encode('utf-8')
                        raise StopAsyncIteration
                    except WebSocketDisconnect:
                        raise StopAsyncIteration
                    except Exception:
                        raise StopAsyncIteration
                        
                async def send(self, message):
                    try:
                        if isinstance(message, str):
                            await self.ws.send_text(message)
                        else:
                            await self.ws.send_bytes(message)
                    except Exception:
                        pass

            client_wrapper = FastAPIWSWrapper(websocket)
            
            # Запускаем двунаправленную пересылку и завершаем при закрытии любого из направлений
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(forward(client_wrapper, target_ws)),
                    asyncio.create_task(forward(target_ws, client_wrapper))
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            
    except Exception as e:
        logger.error(f"Ошибка VNC прокси для {name}: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass
        finally:
            logger.info(f"VNC WebSocket соединение закрыто для ВМ: {name}")
