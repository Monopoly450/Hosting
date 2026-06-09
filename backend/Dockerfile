FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости (curl, git, iptables, util-linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    iptables \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код бэкенда
COPY app/ ./app/

# Запуск приложения через uvicorn
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
