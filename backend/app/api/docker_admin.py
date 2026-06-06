from fastapi import APIRouter, HTTPException, Depends
from app.core.docker_client import HostDockerClient

router = APIRouter()

def get_docker_client():
    client = HostDockerClient()
    if not client.is_available():
        raise HTTPException(status_code=503, detail="Служба Docker недоступна на хосте.")
    return client

@router.get("/containers")
def list_containers(client: HostDockerClient = Depends(get_docker_client)):
    """Получить список всех контейнеров на хост-системе"""
    try:
        return client.list_containers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/containers/{container_id}/{action}")
def manage_container(container_id: str, action: str, client: HostDockerClient = Depends(get_docker_client)):
    """Выполнить действие (start/stop/restart) над контейнером"""
    if action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail="Неверное действие. Допустимы: start, stop, restart")
        
    try:
        return client.manage_container(container_id, action)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
