"""Каталог приложений «в один клик» и генерация cloud-init для их деплоя.

Каждое приложение — самодостаточный docker-compose (приложение + его БД, если
нужна). Деплой поднимает выделенную ВМ, пишет compose и .env и запускает
`docker compose up -d`. Секретные env-переменные генерируются автоматически,
поэтому установка действительно «в один клик».
"""
import os
import secrets

# ---- env-схема: {key, label, default, secret, generate} ----
# secret=True прячем в API; generate=True — если значение не задано, генерируем.


def _gen():
    return secrets.token_hex(16)


CATALOG = [
    {
        "id": "wordpress",
        "name": "WordPress",
        "description": "Самая популярная CMS для сайтов и блогов (с MariaDB).",
        "category": "CMS",
        "icon": "📝",
        "app_port": 8080,
        "env": [
            {"key": "DB_PASSWORD", "label": "Пароль БД", "default": "", "secret": True, "generate": True},
        ],
        "compose": """services:
  db:
    image: mariadb:11
    restart: always
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: ${DB_PASSWORD}
      MYSQL_RANDOM_ROOT_PASSWORD: "1"
    volumes:
      - db_data:/var/lib/mysql
  wordpress:
    image: wordpress:6
    restart: always
    depends_on: [db]
    ports:
      - "8080:80"
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: ${DB_PASSWORD}
      WORDPRESS_DB_NAME: wordpress
      WORDPRESS_CONFIG_EXTRA: |
        define('WP_HOME', '${PUBLIC_URL}');
        define('WP_SITEURL', '${PUBLIC_URL}');
    volumes:
      - wp_data:/var/www/html
volumes:
  db_data:
  wp_data:
""",
    },
    {
        "id": "ghost",
        "name": "Ghost",
        "description": "Современная платформа для блогов и рассылок.",
        "category": "CMS",
        "icon": "👻",
        "app_port": 2368,
        "env": [],
        "compose": """services:
  ghost:
    image: ghost:5
    restart: always
    ports:
      - "2368:2368"
    environment:
      NODE_ENV: production
      url: ${PUBLIC_URL}
    volumes:
      - ghost_data:/var/lib/ghost/content
volumes:
  ghost_data:
""",
    },
    {
        "id": "nextcloud",
        "name": "Nextcloud",
        "description": "Собственное облако для файлов, календаря и контактов (с PostgreSQL).",
        "category": "Файлы",
        "icon": "☁️",
        "app_port": 8081,
        "env": [
            {"key": "DB_PASSWORD", "label": "Пароль БД", "default": "", "secret": True, "generate": True},
        ],
        "compose": """services:
  db:
    image: postgres:16-alpine
    restart: always
    environment:
      POSTGRES_DB: nextcloud
      POSTGRES_USER: nextcloud
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/postgresql/data
  app:
    image: nextcloud:29-apache
    restart: always
    depends_on: [db]
    ports:
      - "8081:80"
    environment:
      POSTGRES_HOST: db
      POSTGRES_DB: nextcloud
      POSTGRES_USER: nextcloud
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      NEXTCLOUD_TRUSTED_DOMAINS: ${PUBLIC_HOST}
      OVERWRITEHOST: ${PUBLIC_HOST}
      OVERWRITEPROTOCOL: http
    volumes:
      - nc_data:/var/www/html
volumes:
  db_data:
  nc_data:
""",
    },
    {
        "id": "n8n",
        "name": "n8n",
        "description": "No-code автоматизация и интеграции (аналог Zapier).",
        "category": "Автоматизация",
        "icon": "🔗",
        "app_port": 5678,
        "env": [],
        "compose": """services:
  n8n:
    image: n8nio/n8n:latest
    restart: always
    ports:
      - "5678:5678"
    environment:
      N8N_SECURE_COOKIE: "false"
      WEBHOOK_URL: ${PUBLIC_URL}
    volumes:
      - n8n_data:/home/node/.n8n
volumes:
  n8n_data:
""",
    },
    {
        "id": "uptime-kuma",
        "name": "Uptime Kuma",
        "description": "Красивый монитор доступности сайтов и сервисов.",
        "category": "Мониторинг",
        "icon": "📈",
        "app_port": 3001,
        "env": [],
        "compose": """services:
  uptime-kuma:
    image: louislam/uptime-kuma:1
    restart: always
    ports:
      - "3001:3001"
    volumes:
      - kuma_data:/app/data
volumes:
  kuma_data:
""",
    },
    {
        "id": "vaultwarden",
        "name": "Vaultwarden",
        "description": "Лёгкий сервер паролей, совместимый с Bitwarden.",
        "category": "Безопасность",
        "icon": "🔐",
        "app_port": 8082,
        "env": [
            {"key": "ADMIN_TOKEN", "label": "Admin token", "default": "", "secret": True, "generate": True},
        ],
        "compose": """services:
  vaultwarden:
    image: vaultwarden/server:latest
    restart: always
    ports:
      - "8082:80"
    environment:
      ADMIN_TOKEN: ${ADMIN_TOKEN}
      DOMAIN: ${PUBLIC_URL}
    volumes:
      - vw_data:/data
volumes:
  vw_data:
""",
    },
    {
        "id": "postgres",
        "name": "PostgreSQL",
        "description": "Реляционная СУБД PostgreSQL 16 в отдельной ВМ.",
        "category": "Базы данных",
        "icon": "🐘",
        "app_port": 5432,
        "env": [
            {"key": "POSTGRES_PASSWORD", "label": "Пароль postgres", "default": "", "secret": True, "generate": True},
        ],
        "compose": """services:
  db:
    image: postgres:16
    restart: always
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
volumes:
  pg_data:
""",
    },
    {
        "id": "redis",
        "name": "Redis",
        "description": "Быстрое key-value хранилище и кэш.",
        "category": "Базы данных",
        "icon": "🧱",
        "app_port": 6379,
        "env": [],
        "compose": """services:
  redis:
    image: redis:7
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
volumes:
  redis_data:
""",
    },
]

_BY_ID = {a["id"]: a for a in CATALOG}


def get_catalog() -> list:
    """Публичный вид каталога (без compose и без секретов)."""
    out = []
    for a in CATALOG:
        out.append({
            "id": a["id"], "name": a["name"], "description": a["description"],
            "category": a["category"], "icon": a["icon"], "app_port": a["app_port"],
            "env": [{"key": e["key"], "label": e["label"],
                     "secret": e.get("secret", False), "generate": e.get("generate", False)}
                    for e in a["env"]],
        })
    return out


def get_app(app_id: str):
    return _BY_ID.get(app_id)


def resolve_env(app: dict, overrides: dict) -> dict:
    """Собирает финальные значения env: пользовательские переопределения,
    иначе default, иначе генерация (для generate=True)."""
    overrides = overrides or {}
    resolved = {}
    for e in app["env"]:
        val = overrides.get(e["key"])
        if not val:
            val = e.get("default") or ""
        if not val and e.get("generate"):
            val = _gen()
        resolved[e["key"]] = val
    return resolved


def default_host() -> str:
    """IP/хост, по которому пользователь достучится до приложения снаружи."""
    return os.getenv("AEGIS_HOST_IP") or os.getenv("HOST_IP") or "127.0.0.1"


def add_public_url(env: dict, host: str, ext_port: int) -> dict:
    """Добавляет в env публичный адрес приложения.

    Многим приложениям (Ghost, WordPress, Nextcloud, n8n, Vaultwarden) нужно
    знать свой внешний URL, иначе они генерируют ссылки на localhost. Внешний
    порт известен только после создания ВМ, поэтому подставляем его здесь.
    """
    public_host = f"{host}:{ext_port}"
    env = dict(env)
    env["PUBLIC_HOST"] = public_host
    env["PUBLIC_URL"] = f"http://{public_host}"
    return env


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.splitlines())


def build_marketplace_cloud_init(app: dict, env: dict, password: str, default_user: str = "ubuntu") -> str:
    """cloud-init: ставит docker, пишет compose и .env, поднимает стек."""
    env_content = "\n".join(f"{k}={v}" for k, v in env.items())
    compose_block = _indent(app["compose"], 6)
    env_block = _indent(env_content, 6) if env_content else "      # (без переменных)"

    return f"""#cloud-config
ssh_pwauth: True
disable_root: false
chpasswd:
  list: |
    root:{password}
    {default_user}:{password}
  expire: False
users:
  - default
packages:
  - docker.io
  - docker-compose-v2
write_files:
  - path: /opt/app/docker-compose.yml
    content: |
{compose_block}
  - path: /opt/app/.env
    content: |
{env_block}
  - path: /etc/netplan/99-dhcp.yaml
    content: |
      network:
        version: 2
        ethernets:
          all-eth:
            match:
              name: "e*"
            dhcp4: true
runcmd:
  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
  - systemctl restart ssh || systemctl restart sshd || true
  - (netplan apply || systemctl restart systemd-networkd) || true
  - while ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; do sleep 2; done
  - apt-get update || true
  - systemctl enable --now docker 2>/dev/null || true
  - usermod -aG docker {default_user} 2>/dev/null || true
  - cd /opt/app && (docker compose up -d || docker-compose up -d) || true
  - (apt-get install -y qemu-guest-agent && systemctl enable --now qemu-guest-agent) || true
"""
