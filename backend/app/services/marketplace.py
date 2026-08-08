"""Каталог приложений «в один клик» и генерация cloud-init для их деплоя.

В каталоге два вида записей, и различает их поле "kind":

* "compose" (по умолчанию) — самодостаточный docker-compose (приложение + его
  БД, если нужна). Деплой поднимает выделенную ВМ, пишет compose и .env и
  запускает `docker compose up -d`. Секретные env-переменные генерируются
  автоматически, поэтому установка действительно «в один клик».

* "template" — окружение из app.services.os_profiles (LAMP, LEMP, Node.js,
  Python, Docker, Portainer, Zabbix). Это не контейнеризованное приложение, а
  набор системных пакетов и служб, поэтому подменять его самодельным compose
  было бы неправдой: LAMP — это системный Apache и MariaDB, а не пара
  контейнеров. Для таких записей API кладёт имя шаблона в
  VMTask.cloud_init_template и НЕ трогает custom_user_data — cloud-init собирает
  воркер тем же generate_linux_manifest, что и для обычной ВМ. Второго сборщика
  здесь нет намеренно: он бы разошёлся с основным при первой же правке.

Все записи разворачиваются на Ubuntu — это единственная ОС, на которой шаблоны
предлагаются (см. TEMPLATE_OFFERED_OS в os_profiles).
"""
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
        # Образ Nextcloud с PostgreSQL весит около гигабайта и при первом
        # запуске ещё разворачивает базу — до этого порт просто не отвечает.
        "note": ("Первый запуск занимает 5–10 минут: скачиваются образы "
                 "Nextcloud и PostgreSQL, затем разворачивается база. "
                 "Пока это идёт, ссылка не открывается — просто подождите."),
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
        # Браузер выдаёт Web Crypto API только в защищённом контексте, а без
        # него хранилище паролей не работает. Это требование приложения, а не
        # нашей установки: по http:// оно не заведётся никогда.
        "requires_https": True,
        "note": ("Требует HTTPS: по IP-адресу интерфейс не запустится. "
                 "Подключите домен на вкладке «Домены и TLS» и открывайте по нему."),
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
    {
        "id": "grafana",
        "name": "Grafana",
        "description": "Дашборды и графики по метрикам из Prometheus, БД и других источников.",
        "category": "Мониторинг",
        "icon": "📊",
        "app_port": 3000,
        # Пароль admin не задаём через env: Grafana сама потребует сменить его
        # при первом входе, и он не окажется ни в cloud-init, ни в логах.
        "note": ("Первый вход — admin / admin, Grafana сразу попросит задать "
                 "новый пароль."),
        "env": [],
        "compose": """services:
  grafana:
    image: grafana/grafana-oss:latest
    restart: always
    ports:
      - "3000:3000"
    environment:
      GF_SERVER_ROOT_URL: ${PUBLIC_URL}
      # Grafana за реверс-прокси (см. вкладку «Домены»): без этого редиректы
      # после логина уводят на localhost.
      GF_SERVER_SERVE_FROM_SUB_PATH: "false"
    volumes:
      - grafana_data:/var/lib/grafana
volumes:
  grafana_data:
""",
    },
]

# --- Окружения из os_profiles, показанные в маркетплейсе -------------------
#
# Раньше их выбирали при создании локальной ВМ («Шаблон окружения»), и это был
# второй, отдельный от маркетплейса путь получить готовую машину — с той же
# сутью, но другим интерфейсом и без предупреждений и заметок каталога. Теперь
# точка входа одна: всё, что можно развернуть в один клик, лежит в
# маркетплейсе. Сами шаблоны остались в os_profiles без изменений — здесь
# только их описание для каталога.
TEMPLATE_APPS = [
    {
        "id": "tpl-lamp", "template": "lamp",
        "name": "LAMP", "description": "Apache + PHP + MariaDB как системные службы (не в контейнерах).",
        "category": "Окружения", "icon": "🅰️", "app_port": 80,
    },
    {
        "id": "tpl-lemp", "template": "lemp",
        "name": "LEMP", "description": "Nginx + PHP-FPM + MariaDB как системные службы.",
        "category": "Окружения", "icon": "🇳", "app_port": 80,
    },
    {
        "id": "tpl-docker", "template": "docker",
        "name": "Docker", "description": "Чистая ВМ с Docker Engine и Compose — база под свои контейнеры.",
        "category": "Окружения", "icon": "🐳", "app_port": 80,
        "note": "Своего веб-интерфейса нет: это заготовка под ваши контейнеры. Доступ по SSH.",
    },
    {
        "id": "tpl-portainer", "template": "portainer",
        "name": "Portainer", "description": "Веб-интерфейс управления Docker-контейнерами.",
        "category": "Окружения", "icon": "🧭", "app_port": 9000,
    },
    {
        "id": "tpl-grafana", "template": "grafana",
        "name": "Grafana (в Docker)", "description": "То же, что приложение Grafana, но поверх шаблона Docker — если нужна ВМ с Docker и Grafana рядом.",
        "category": "Окружения", "icon": "📊", "app_port": 3000,
        "note": "Первый вход — admin / admin, Grafana сразу попросит задать новый пароль.",
    },
    {
        "id": "tpl-nodejs", "template": "nodejs",
        "name": "Node.js 20 LTS", "description": "Node.js 20 и pm2 — окружение под своё приложение.",
        "category": "Окружения", "icon": "🟩", "app_port": 3000,
        "note": "Своего веб-интерфейса нет: это окружение под ваш код. Доступ по SSH.",
    },
    {
        "id": "tpl-python", "template": "python",
        "name": "Python 3", "description": "Python 3 с pip, venv и gunicorn — окружение под своё приложение.",
        "category": "Окружения", "icon": "🐍", "app_port": 8000,
        "note": "Своего веб-интерфейса нет: это окружение под ваш код. Доступ по SSH.",
    },
    {
        "id": "tpl-postgresql", "template": "postgresql",
        "name": "PostgreSQL (системный)", "description": "PostgreSQL как системная служба, а не в контейнере.",
        "category": "Окружения", "icon": "🐘", "app_port": 5432,
    },
    {
        "id": "tpl-redis", "template": "redis",
        "name": "Redis (системный)", "description": "Redis как системная служба, а не в контейнере.",
        "category": "Окружения", "icon": "🧱", "app_port": 6379,
    },
    {
        "id": "tpl-wordpress", "template": "wordpress",
        "name": "WordPress (LAMP)", "description": "WordPress на системном Apache + MariaDB, без контейнеров.",
        "category": "Окружения", "icon": "📝", "app_port": 80,
    },
    {
        "id": "tpl-zabbix", "template": "zabbix",
        "name": "Zabbix", "description": "Сервер мониторинга Zabbix с веб-интерфейсом на /zabbix.",
        "category": "Окружения", "icon": "🛰️", "app_port": 80,
        "note": "Веб-интерфейс открывается по пути /zabbix, а не в корне сайта.",
    },
]

for _app in TEMPLATE_APPS:
    _app.setdefault("kind", "template")
    _app.setdefault("env", [])
    CATALOG.append(_app)

_BY_ID = {a["id"]: a for a in CATALOG}


def get_catalog() -> list:
    """Публичный вид каталога (без compose и без секретов)."""
    out = []
    for a in CATALOG:
        out.append({
            "id": a["id"], "name": a["name"], "description": a["description"],
            "category": a["category"], "icon": a["icon"], "app_port": a["app_port"],
            "kind": a.get("kind", "compose"),
            # Предупреждения показываем ДО установки: иначе пользователь узнаёт
            # об ограничении, только наткнувшись на нерабочий интерфейс.
            "requires_https": a.get("requires_https", False),
            "note": a.get("note"),
            "env": [{"key": e["key"], "label": e["label"],
                     "secret": e.get("secret", False), "generate": e.get("generate", False)}
                    for e in a["env"]],
        })
    return out


def is_template_app(app: dict) -> bool:
    return app.get("kind") == "template"


def get_app(app_id: str):
    return _BY_ID.get(app_id)


def sanitize_env_value(value) -> str:
    """Значение уходит строкой в .env внутри cloud-init. Перевод строки позволил
    бы дописать в файл произвольные переменные, поэтому такие значения отклоняем
    (а не «чиним» молча — пользователь должен увидеть ошибку)."""
    val = "" if value is None else str(value)
    if any(ch in val for ch in ("\n", "\r", "\0")):
        raise ValueError("Значение переменной не может содержать перенос строки")
    return val


def resolve_env(app: dict, overrides: dict) -> dict:
    """Собирает финальные значения env: пользовательские переопределения,
    иначе default, иначе генерация (для generate=True).

    Учитываются только переменные из схемы приложения — произвольные ключи
    от пользователя в .env не попадают.
    """
    overrides = overrides or {}
    resolved = {}
    for e in app["env"]:
        val = sanitize_env_value(overrides.get(e["key"]))
        if not val:
            val = e.get("default") or ""
        if not val and e.get("generate"):
            val = _gen()
        resolved[e["key"]] = val
    return resolved


def default_host() -> str:
    """IP/хост, по которому пользователь достучится до приложения снаружи."""
    from app.core.netutils import detect_host_ip
    return detect_host_ip()


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
    """cloud-init: ставит docker, пишет compose и .env, поднимает стек.

    Сеть здесь не настраивается: её задаёт networkData в самом манифесте ВМ
    (см. build_network_data в app.services.cloudinit), одинаково для обычных
    ВМ, маркетплейса и деплоя из GitHub. Раньше каждый сборщик писал свой
    файл netplan, и их приходилось держать синхронными вручную.
    """
    env_content = "\n".join(f"{k}={v}" for k, v in env.items())
    compose_block = _indent(app["compose"], 6)
    env_block = _indent(env_content, 6) if env_content else "      # (без переменных)"

    from app.services.cloudinit import (GUEST_AGENT_RETRY_RUNCMD, WAIT_NETWORK_RUNCMD,
                                        COMPOSE_UP_RUNCMD)

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
package_update: true
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
runcmd:
  - sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
  - sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
  - systemctl restart ssh || systemctl restart sshd || true
{WAIT_NETWORK_RUNCMD}
  - apt-get update || true
  - systemctl enable --now docker 2>/dev/null || true
  - usermod -aG docker {default_user} 2>/dev/null || true
{COMPOSE_UP_RUNCMD}
{GUEST_AGENT_RETRY_RUNCMD}
"""
