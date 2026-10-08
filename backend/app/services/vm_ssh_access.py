"""Password-based panel SSH must never probe a key-only guest."""
from fastapi import HTTPException


def ssh_access_policy(task=None, os_type=None):
    os_type = (getattr(task, "os_type", None) or os_type or "").lower()
    if os_type in ("windows", "truenas"):
        return {"auth_mode": "unsupported", "web_terminal_enabled": False,
                "reason": "unsupported_os"}
    if task is not None and (getattr(task, "ssh_key", None) or "").strip():
        return {"auth_mode": "publickey", "web_terminal_enabled": False,
                "reason": "own_key"}
    custom = getattr(task, "custom_user_data", None) if task is not None else None
    if custom:
        from app.services.vm_inputs import cloud_config
        try:
            if cloud_config(custom).get("ssh_pwauth") is False:
                return {"auth_mode": "publickey", "web_terminal_enabled": False,
                        "reason": "password_disabled"}
        except (ValueError, TypeError):
            # Older records may contain scripts/MIME rather than cloud-config.
            # Their effective SSH policy cannot be inferred from this input.
            pass
    return {"auth_mode": "password", "web_terminal_enabled": True, "reason": None}


def read_ssh_access(name, os_type=None):
    from app.db import SessionLocal
    from app.models.models import VMTask
    with SessionLocal() as db:
        task = db.query(VMTask).filter(VMTask.name == name).first()
        return ssh_access_policy(task, os_type)


def require_web_ssh(name, os_type=None):
    policy = read_ssh_access(name, os_type)
    if not policy["web_terminal_enabled"]:
        message = ("Веб-терминал недоступен для этой ОС." if policy["reason"] == "unsupported_os" else
                   "Парольный SSH панели отключён: используйте свой приватный ключ во внешнем SSH-клиенте или VNC.")
        raise HTTPException(status_code=409, detail=message)
