FROM python:3.11-slim

ARG KUBECTL_VERSION=v1.36.5

WORKDIR /app

# Устанавливаем системные зависимости (curl, git, iptables, util-linux, lvm2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    iptables \
    util-linux \
    lvm2 \
    && ARCH=$(uname -m) \
    && if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; fi \
    && if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi \
    && curl -sSL "https://dl.min.io/client/mc/release/linux-${ARCH}/mc" -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc \
    && rm -rf /var/lib/apt/lists/*

# SQL-консоль и восстановление БД запускают kubectl exec из backend/worker.
# Версия фиксирована; для другого кластера её можно задать через build-arg.
RUN kubectl_arch="$(dpkg --print-architecture)" \
    && curl -fSL --retry 3 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${kubectl_arch}/kubectl" -o /usr/local/bin/kubectl \
    && curl -fSL --retry 3 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${kubectl_arch}/kubectl.sha256" -o /tmp/kubectl.sha256 \
    && printf '%s  %s\n' "$(cat /tmp/kubectl.sha256)" /usr/local/bin/kubectl | sha256sum --check \
    && chmod 755 /usr/local/bin/kubectl \
    && kubectl version --client --output=yaml \
    && rm /tmp/kubectl.sha256

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код бэкенда
COPY app/ ./app/

# Запуск приложения через uvicorn
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
