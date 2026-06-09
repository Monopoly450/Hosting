from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
import docker
import os
import subprocess
from typing import Optional

router = APIRouter()

# Инициализируем Docker клиент
def get_docker_client():
    try:
        client = docker.DockerClient(base_url="unix://var/run/docker.sock", timeout=30)
        client.ping()
        return client
    except Exception as e:
        return None

def get_repo_host_path(client) -> str:
    try:
        container = client.containers.get("hosting-backend")
        for mount in container.attrs.get("Mounts", []):
            if mount["Destination"] == "/app/data":
                return mount["Source"].rsplit("/", 1)[0]
    except Exception as e:
        pass
    # Fallback на дефолтный путь
    return os.getenv("REPO_HOST_PATH", "/Users/vladislavkarasev/Documents/Хостинг")

class CommandRequest(BaseModel):
    command: str

@router.get("/git-info")
def get_git_info():
    """Возвращает информацию о текущем состоянии Git-репозитория на хосте"""
    client = get_docker_client()
    if not client:
        # Если докер недоступен, попробуем локальный git в контейнере
        try:
            log_res = subprocess.run(
                ["git", "log", "-n", "1", "--format=%H|%an|%ad|%s"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            parts = log_res.split('|', 3)
            
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            
            status_res = subprocess.run(
                ["git", "status", "--short"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            
            return {
                "branch": branch,
                "commit_hash": parts[0] if len(parts) > 0 else "N/A",
                "author": parts[1] if len(parts) > 1 else "N/A",
                "date": parts[2] if len(parts) > 2 else "N/A",
                "subject": parts[3] if len(parts) > 3 else "N/A",
                "status_text": "Local container mode (Docker unavailable)",
                "local_changes": status_res
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка локального Git: {str(e)}")
    
    repo_path = "/app/repo"
    try:
        # Запустим команды в смонтированной папке репозитория
        log_res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H|%an|%ad|%s"], 
            cwd=repo_path, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        parts = log_res.split('|', 3)
        commit_hash = parts[0] if len(parts) > 0 else "N/A"
        author = parts[1] if len(parts) > 1 else "N/A"
        date = parts[2] if len(parts) > 2 else "N/A"
        subject = parts[3] if len(parts) > 3 else "N/A"
        
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
            cwd=repo_path, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        
        status_res = subprocess.run(
            ["git", "status", "--short"], 
            cwd=repo_path, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        
        # Для git fetch && git status -uno мы используем nsenter на хосте
        host_repo_path = "/Users/vladislavkarasev/Documents/Хостинг"
        git_fetch_cmd = f"cd {host_repo_path} && git fetch && git status -uno"
        nsenter_cmd = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c", git_fetch_cmd]
        fetch_res = subprocess.run(nsenter_cmd, capture_output=True, text=True, timeout=10).stdout.strip()
        
        up_to_date = "your branch is up to date" in fetch_res.lower()
        behind = "behind" in fetch_res.lower()
        ahead = "ahead" in fetch_res.lower()
        
        status_text = "Up to date"
        if behind:
            status_text = "Updates available on GitHub"
        elif ahead:
            status_text = "Ahead of origin (unpushed commits)"
        elif not up_to_date:
            status_text = "Modified or divergent"
            
        return {
            "branch": branch,
            "commit_hash": commit_hash,
            "author": author,
            "date": date,
            "subject": subject,
            "status_text": status_text,
            "local_changes": status_res
        }
    except Exception as e:
        try:
            log_res = subprocess.run(
                ["git", "log", "-n", "1", "--format=%H|%an|%ad|%s"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            parts = log_res.split('|', 3)
            
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            
            status_res = subprocess.run(
                ["git", "status", "--short"], 
                cwd="/app/repo", capture_output=True, text=True, timeout=5
            ).stdout.strip()
            
            return {
                "branch": branch,
                "commit_hash": parts[0] if len(parts) > 0 else "N/A",
                "author": parts[1] if len(parts) > 1 else "N/A",
                "date": parts[2] if len(parts) > 2 else "N/A",
                "subject": parts[3] if len(parts) > 3 else "N/A",
                "status_text": "Local container mode (Fallback)",
                "local_changes": status_res
            }
        except Exception as local_err:
            raise HTTPException(status_code=500, detail=f"Ошибка Git: {str(e)} (Локально: {str(local_err)})")

@router.post("/git-pull")
def git_pull():
    """Выполняет git pull и перезапуск/пересборку docker-compose на хосте"""
    host_repo_path = "/Users/vladislavkarasev/Documents/Хостинг"
    cmd = f"cd {host_repo_path} && git pull && docker compose up -d --build"
    try:
        nsenter_cmd = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c", cmd]
        res = subprocess.run(nsenter_cmd, capture_output=True, text=True, timeout=60)
        output = res.stdout + res.stderr
        if res.returncode == 0:
            return {"status": "success", "output": output}
        else:
            raise Exception(f"nsenter failed: {output}")
    except Exception as e:
        try:
            git_pull_res = subprocess.run(["git", "pull"], cwd="/app/repo", capture_output=True, text=True, timeout=15)
            client = get_docker_client()
            restarted = []
            if client:
                for c in client.containers.list(all=True):
                    if c.name in ["hosting-frontend", "vds-frontend", "aegis-orchestrator", "hosting-backend"]:
                        c.restart(timeout=10)
                        restarted.append(c.name)
            return {
                "status": "partial_success",
                "output": f"Git pull (local container):\n{git_pull_res.stdout}\n{git_pull_res.stderr}\n\nРестарт контейнеров: {', '.join(restarted)}"
            }
        except Exception as local_err:
            raise HTTPException(status_code=500, detail=f"Ошибка обновления: {str(e)} (Локально: {str(local_err)})")

@router.get("/logs")
def get_service_logs(service: str = Query(..., description="Имя сервиса"), tail: int = 200):
    """Возвращает последние строки логов указанного контейнера"""
    client = get_docker_client()
    if not client:
        raise HTTPException(status_code=503, detail="Docker Daemon недоступен.")
    
    service_map = {
        "backend": "hosting-backend",
        "frontend": "hosting-frontend",
        "orchestrator": "aegis-orchestrator",
        "vds-frontend": "vds-frontend",
        "db": "aegis-db"
    }
    
    container_name = service_map.get(service, service)
    try:
        container = client.containers.get(container_name)
        logs = container.logs(tail=tail, stdout=True, stderr=True)
        return {"service": service, "container": container_name, "logs": logs.decode('utf-8')}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Не удалось получить логи для {container_name}: {str(e)}")

@router.post("/execute-command")
def execute_command(req: CommandRequest):
    """Выполняет произвольную команду на хост-сервере через nsenter"""
    cmd = req.command
    forbidden_keywords = ["rm -rf /", "mkfs", "dd ", "shutdown", "reboot", "poweroff"]
    for kw in forbidden_keywords:
        if kw in cmd:
            raise HTTPException(status_code=400, detail=f"Команда содержит запрещенный токен: '{kw}'")
            
    try:
        # Выполняем nsenter прямо через subprocess.run из привилегированного контейнера
        nsenter_cmd = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c", cmd]
        res = subprocess.run(nsenter_cmd, capture_output=True, text=True, timeout=30)
        return {"status": "success", "output": res.stdout + res.stderr}
    except Exception as e:
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return {"status": "local_success", "output": f"Stdout:\n{res.stdout}\n\nStderr:\n{res.stderr}"}
        except Exception as local_err:
            raise HTTPException(status_code=500, detail=f"Ошибка выполнения на хосте: {str(e)} (Локально: {str(local_err)})")
