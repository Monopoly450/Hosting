import os
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
    # Раньше пароль не проверялся вообще — можно было завести ящик с пустым
    # паролем. Управляющие символы запрещаем: они не наберутся в почтовом
    # клиенте и ломают передачу аргументов серверу.
    password: str = Field(..., min_length=8, max_length=128,
                          description="Пароль для почтового ящика (минимум 8 символов)")

class MailboxResponse(BaseModel):
    id: int
    email: str
    quota_mb: int
    owner_username: str
    created_at: str

def manage_docker_mailserver(action: str, email: str, password: str = None) -> bool:
    """Управление почтовыми ящиками внутри контейнера docker-mailserver.

    Команда передаётся СПИСКОМ аргументов: строку docker SDK разбирает через
    shlex, и тогда пароль с пробелом молча превращался в два аргумента (ящик
    заводился с другим паролем), а пароль с апострофом ронял разбор с
    ValueError. Со списком значение уходит как есть.
    """
    if action == "add":
        cmd = ["setup", "email", "add", email, password]
    elif action == "del":
        cmd = ["setup", "email", "del", email]
    else:
        return False

    try:
        client = docker.from_env()
        container = client.containers.get("aegis-mailserver")
        exit_code, output = container.exec_run(cmd)
        # Пароль в лог не пишем
        logger.info(f"Mailserver {action} {email}: exit={exit_code}, "
                    f"output={output.decode(errors='ignore').strip()[:200]}")
        return exit_code == 0
    except Exception as e:
        # Раньше здесь возвращался True «для локальной разработки»: панель
        # рапортовала об успехе и сохраняла в БД ящик, которого на сервере нет.
        # Пользователь потом не мог войти в почту без каких-либо объяснений.
        if os.getenv("MAIL_ALLOW_OFFLINE", "").lower() in ("1", "true", "yes"):
            logger.warning(f"docker-mailserver недоступен, MAIL_ALLOW_OFFLINE включён: {e}")
            return True
        logger.error(f"docker-mailserver недоступен: {e}")
        return False

@router.post("", response_model=MailboxResponse, status_code=status.HTTP_201_CREATED)
def create_mailbox(req: MailboxCreateRequest, current_user: User = Depends(get_current_user)):
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", req.email):
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат email адреса."
        )
    if any(ch in req.password for ch in ("\n", "\r", "\0", "\t")):
        raise HTTPException(
            status_code=400,
            detail="Пароль не может содержать переносы строк и табуляцию."
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
        from app.core.auth import hash_password
        new_mail = UserMailbox(
            email=req.email,
            password_hash=hash_password(req.password),
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
