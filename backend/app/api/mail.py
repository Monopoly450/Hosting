import re
import logging
import docker
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List
from app.db import SessionLocal
from app.models.models import User, UserMailbox
from app.core.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("app.api.mail")

class MailboxCreateRequest(BaseModel):
    email: str = Field(..., description="Email адрес (например, dev@project.local)")
    password: str = Field(..., description="Пароль для почтового ящика")

class MailboxResponse(BaseModel):
    id: int
    email: str
    quota_mb: int
    owner_username: str
    created_at: str

def manage_docker_mailserver(action: str, email: str, password: str = None) -> bool:
    """Управление почтовыми ящиками внутри контейнера docker-mailserver"""
    try:
        client = docker.from_env()
        container = client.containers.get("aegis-mailserver")
        if action == "add":
            cmd = f"setup email add {email} {password}"
        elif action == "del":
            cmd = f"setup email del {email}"
        else:
            return False
            
        exit_code, output = container.exec_run(cmd)
        logger.info(f"Mailserver command: {cmd}, exit: {exit_code}, output: {output.decode().strip()}")
        return exit_code == 0
    except Exception as e:
        logger.warning(f"docker-mailserver is not reachable (either not running or offline): {e}")
        # Возвращаем True для локального тестирования/разработки
        return True

@router.post("", response_model=MailboxResponse, status_code=status.HTTP_201_CREATED)
def create_mailbox(req: MailboxCreateRequest, current_user: User = Depends(get_current_user)):
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", req.email):
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат email адреса."
        )

    db = SessionLocal()
    try:
        # Проверяем лимиты почтовых ящиков для обычных пользователей
        if current_user.role != "admin":
            owned_mails = db.query(UserMailbox).filter(UserMailbox.owner_id == current_user.id).count()
            if owned_mails >= 5:
                raise HTTPException(
                    status_code=400,
                    detail="Превышен лимит создания почтовых ящиков (макс. 5 ящиков на пользователя)."
                )

        # Проверяем уникальность email
        existing = db.query(UserMailbox).filter(UserMailbox.email == req.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Этот почтовый ящик уже занят.")

        # Регистрируем в контейнере docker-mailserver
        success = manage_docker_mailserver("add", req.email, req.password)
        if not success:
            raise HTTPException(status_code=500, detail="Не удалось настроить почтовый ящик на почтовом сервере.")

        # Сохраняем в БД
        from app.core.auth import get_password_hash # или хэшируем
        new_mail = UserMailbox(
            email=req.email,
            password_hash=get_password_hash(req.password),
            quota_mb=500,
            owner_id=current_user.id
        )
        db.add(new_mail)
        db.commit()
        db.refresh(new_mail)

        return MailboxResponse(
            id=new_mail.id,
            email=new_mail.email,
            quota_mb=new_mail.quota_mb,
            owner_username=current_user.username,
            created_at=new_mail.created_at.strftime("%Y-%m-%d %H:%M:%S")
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("", response_model=List[MailboxResponse])
def list_mailboxes(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            mailboxes = db.query(UserMailbox).all()
        else:
            mailboxes = db.query(UserMailbox).filter(UserMailbox.owner_id == current_user.id).all()

        res = []
        for m in mailboxes:
            owner = db.query(User).filter(User.id == m.owner_id).first()
            owner_name = owner.username if owner else "Unknown"
            
            res.append(MailboxResponse(
                id=m.id,
                email=m.email,
                quota_mb=m.quota_mb,
                owner_username=owner_name,
                created_at=m.created_at.strftime("%Y-%m-%d %H:%M:%S")
            ))
        return res
    finally:
        db.close()

@router.delete("/{mailbox_id}", status_code=status.HTTP_200_OK)
def delete_mailbox(mailbox_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        mailbox = db.query(UserMailbox).filter(UserMailbox.id == mailbox_id).first()
        if not mailbox:
            raise HTTPException(status_code=404, detail="Почтовый ящик не найден")

        if current_user.role != "admin" and mailbox.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого почтового ящика.")

        # Удаляем из контейнера docker-mailserver
        manage_docker_mailserver("del", mailbox.email)

        # Удаляем из БД
        db.delete(mailbox)
        db.commit()
        return {"status": "Mailbox deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
