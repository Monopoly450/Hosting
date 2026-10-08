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
    && rm -rf /var/lib/apt/lists/*

# dl.min.io больше не раздаёт mc (HTTP 410). curl без -f сохранял ответ
# сервера вместо ELF, и контейнер запускался с неисправным /usr/local/bin/mc.
# Официальные release assets GitHub, фиксированные версия и SHA-256.
# Архитектура берётся из целевого Debian-образа, не из ядра build-хоста.
RUN mc_arch="$(dpkg --print-architecture)" \
    && mc_release="RELEASE.2025-08-13T08-35-41Z" \
    && case "$mc_arch" in \
        amd64) mc_sha="01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891" ;; \
        arm64) mc_sha="14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c" ;; \
        *) printf 'Unsupported mc architecture: %s\n' "$mc_arch" >&2; exit 1 ;; \
    esac \
    && curl -fSL --retry 3 "https://github.com/minio/mc/releases/download/${mc_release}/mc.linux-${mc_arch}.${mc_release}" -o /usr/local/bin/mc \
    && printf '%s  /usr/local/bin/mc\n' "$mc_sha" | sha256sum --check \
    && chmod 755 /usr/local/bin/mc \
    && mc --version

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
