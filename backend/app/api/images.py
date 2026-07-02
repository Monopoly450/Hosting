import os
import shutil
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, status, Depends
from typing import List
from app.core.auth import get_current_user, verify_admin_token
from app.models.models import User

router = APIRouter()
logger = logging.getLogger("app.images")

# Директория для хранения образов
IMAGES_DIR = os.getenv("IMAGES_DIR", "/app/data/images")

# Создаем папку, если ее нет
os.makedirs(IMAGES_DIR, exist_ok=True)

# Список поддерживаемых расширений
ALLOWED_EXTENSIONS = {".qcow2", ".img", ".iso", ".raw"}

@router.get("", response_model=List[dict])
def list_images(current_user: User = Depends(get_current_user)):
    """Получить список всех загруженных образов"""
    try:
        images = []
        for filename in os.listdir(IMAGES_DIR):
            file_path = os.path.join(IMAGES_DIR, filename)
            if os.path.isfile(file_path):
                # Проверяем расширение
                _, ext = os.path.splitext(filename)
                if ext.lower() in ALLOWED_EXTENSIONS:
                    stat = os.stat(file_path)
                    size_mb = round(stat.st_size / (1024 * 1024), 2)
                    
                    # Генерируем URL раздачи статики (бэкенд будет раздавать эту папку)
                    # В продакшене (docker-compose host mode) хост доступен как localhost:8000
                    # Мы возвращаем относительный путь, а фронтенд сам подставит нужный хост
                    download_url = f"/static/images/{filename}"
                    
                    images.append({
                        "filename": filename,
                        "size_mb": size_mb,
                        "size_gb": round(size_mb / 1024, 2),
                        "url": download_url,
                        "extension": ext.lower()[1:]
                    })
        return images
    except Exception as e:
        logger.error(f"Ошибка чтения директории образов: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_image(file: UploadFile = File(...), admin: str = Depends(verify_admin_token)):
    """Загрузить файл образа на сервер (потоковая запись в файл)"""
    filename = file.filename
    _, ext = os.path.splitext(filename)
    
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Неподдерживаемый тип файла. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}"
        )
        
    dest_path = os.path.join(IMAGES_DIR, filename)
    
    # Записываем файл чанками, чтобы не переполнять RAM
    try:
        logger.info(f"Начало загрузки образа {filename} в {dest_path}...")
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Образ {filename} успешно сохранен.")
        return {"status": "success", "filename": filename, "size_mb": round(os.path.getsize(dest_path) / (1024 * 1024), 2)}
    except Exception as e:
        logger.error(f"Ошибка сохранения файла образа {filename}: {e}")
        # Удаляем битый файл при ошибке
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise HTTPException(status_code=500, detail=f"Ошибка записи на диск: {e}")
    finally:
        file.file.close()

@router.delete("/{filename}")
def delete_image(filename: str, admin: str = Depends(verify_admin_token)):
    """Удалить файл образа с сервера"""
    # Защита от Path Traversal
    filename_safe = os.path.basename(filename)
    file_path = os.path.join(IMAGES_DIR, filename_safe)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Файл {filename_safe} не найден.")
        
    try:
        os.remove(file_path)
        logger.info(f"Удален файл образа: {filename_safe}")
        return {"status": "deleted", "filename": filename_safe}
    except Exception as e:
        logger.error(f"Ошибка удаления образа {filename_safe}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
