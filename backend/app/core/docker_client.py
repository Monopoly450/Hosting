import logging
import docker
from docker.errors import DockerException

logger = logging.getLogger("app.docker_client")

class HostDockerClient:
    def __init__(self):
        self.client = None
        self.connect()

    def connect(self):
        """Пытается подключиться к Docker Daemon через локальный сокет"""
        try:
            # unix://var/run/docker.sock - дефолтный путь в Linux
            self.client = docker.DockerClient(base_url="unix://var/run/docker.sock", timeout=5)
            # Проверяем соединение с помощью простого вызова ping
            self.client.ping()
            logger.info("Успешное подключение к Docker Daemon на хосте.")
        except DockerException as e:
            logger.error(f"Не удалось подключиться к Docker Daemon: {e}")
            self.client = None

    def is_available(self) -> bool:
        if not self.client:
            self.connect()
        return self.client is not None

    def list_containers(self) -> list:
        """Получить список всех контейнеров на хосте (активных и остановленных)"""
        if not self.is_available():
            raise Exception("Docker Daemon недоступен на хосте (проверьте монтирование /var/run/docker.sock)")
        
        try:
            containers = self.client.containers.list(all=True)
            result = []
            for c in containers:
                # Парсим порты в удобный формат
                ports_dict = c.attrs.get("HostConfig", {}).get("PortBindings", {})
                ports = []
                for container_port, host_bindings in ports_dict.items():
                    if host_bindings:
                        host_port = host_bindings[0].get("HostPort")
                        ports.append(f"{host_port}->{container_port}")
                
                result.append({
                    "id": c.id[:12],
                    "full_id": c.id,
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else c.image.id[:12],
                    "status": c.status, # running, exited, paused, etc.
                    "created": c.attrs.get("Created", ""),
                    "ports": ports,
                    "command": " ".join(c.attrs.get("Config", {}).get("Cmd") or [])
                })
            return result
        except Exception as e:
            logger.error(f"Ошибка получения списка контейнеров: {e}")
            raise e

    def manage_container(self, container_id: str, action: str) -> dict:
        """Управление жизненным циклом контейнера (start, stop, restart)"""
        if not self.is_available():
            raise Exception("Docker Daemon недоступен.")
            
        try:
            container = self.client.containers.get(container_id)
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop(timeout=10)
            elif action == "restart":
                container.restart(timeout=10)
            else:
                raise ValueError(f"Неподдерживаемое действие: {action}")
                
            logger.info(f"Выполнено действие {action} для контейнера {container.name} ({container_id})")
            return {"status": "success", "id": container_id, "action": action}
        except Exception as e:
            logger.error(f"Ошибка управления контейнером {container_id} (действие {action}): {e}")
            raise e
