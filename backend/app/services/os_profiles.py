"""Различия между семействами Linux: пакеты, службы, менеджер пакетов.

Раньше шаблоны окружения (LAMP, Docker, Redis и т.д.) подставляли в cloud-init
ОДИН И ТОТ ЖЕ набор пакетов для всех 13 типов ОС — а имена там дебиановские.
На CentOS/Rocky/Alma/Fedora `apache2` и `docker.io` просто не существуют, поэтому
установка пакетов падала, и шаблон молча не срабатывал: ВМ поднималась «чистой»,
без обещанного окружения, без единой ошибки в панели.

Здесь собрано то, что реально отличается между семействами. Если шаблон для
семейства не описан — он для него не поддерживается (см. template_supported),
и это честнее, чем подставить заведомо несуществующие имена пакетов.
"""

# os_type -> семейство. Определяет менеджер пакетов и имена пакетов/служб.
OS_FAMILY = {
    "ubuntu": "debian",
    "debian": "debian",
    "centos": "rhel",
    "bitrix": "rhel",
    "almalinux": "rhel",
    "rocky": "rhel",
    "fedora": "rhel",
    "opensuse": "suse",
    "arch": "arch",
    "alpine": "alpine",
}

# Семейства без systemd — в них бессмысленны systemctl и юниты systemd.
# Alpine использует OpenRC (rc-update / rc-service).
NO_SYSTEMD_FAMILIES = ("alpine",)

# ОС, которые уже разворачивают собственный веб-стек.
#
# bitrix — это не «CentOS, на котором можно что-то развернуть», а установка
# bitrix-env.sh (см. generate_linux_manifest): она разворачивает собственный
# полный стек — nginx как фронтенд, за ним Apache, MySQL и PHP.
OS_WITH_OWN_WEB_STACK = ("bitrix",)

# Шаблоны, которые сами поднимают веб-сервер на порту 80.
#
# Только они и конфликтуют с ОС из списка выше: шаблон LAMP ставил поверх
# Bitrix ЕЩЁ ОДИН Apache, оба стека начинали делить порт 80, выигрывал nginx
# от Bitrix и отдавал «403 Forbidden» — сайт в нём ещё не настроен.
#
# Остальные шаблоны блокировать не за что: Docker сам порты не занимает,
# Portainer слушает 9000, Redis 6379, PostgreSQL 5432 (у Bitrix MySQL на
# 3306), Node.js и Python — просто наборы пакетов. Всё это рядом с Bitrix
# работает, поэтому запрещаем ровно конфликтующее, а не шаблоны целиком.
WEB_STACK_TEMPLATES = ("lamp", "lemp", "wordpress")


def family_of(os_type: str) -> str:
    """Семейство ОС. Неизвестные типы считаем debian-подобными: это поведение
    по умолчанию совпадает с образом по умолчанию (Ubuntu) в LINUX_CLOUD_IMAGES."""
    return OS_FAMILY.get(os_type, "debian")


def has_systemd(os_type: str) -> bool:
    return family_of(os_type) not in NO_SYSTEMD_FAMILIES


def enable_service_cmd(os_type: str, service: str) -> str:
    """Команда «включить и запустить службу» для нужной системы инициализации."""
    if has_systemd(os_type):
        return f"systemctl enable --now {service}"
    # OpenRC (Alpine): добавить в автозапуск + стартовать сейчас
    return f"rc-update add {service} default && rc-service {service} start"


# Имя юнита SSH-сервера. В Debian и Ubuntu он называется ssh, во всех
# остальных семействах — sshd. Раньше команда была «systemctl restart ssh ||
# systemctl restart sshd», то есть на RHEL первая попытка всегда падала с
# «Unit ssh.service not found» в логе cloud-init: работало за счёт запасного
# варианта, но каждый лог начинался с пугающей ошибки.
SSH_SERVICE = {
    "debian": "ssh",
    "rhel": "sshd",
    "suse": "sshd",
    "arch": "sshd",
    "alpine": "sshd",
}


def restart_ssh_cmd(os_type: str) -> str:
    """Перезапуск SSH-сервера правильным для системы способом."""
    service = SSH_SERVICE.get(family_of(os_type), "ssh")
    if has_systemd(os_type):
        return f"systemctl restart {service} || true"
    return f"rc-service {service} restart || true"


# Менеджер пакетов семейства — команда установки одного пакета.
# Порядок важен: сначала пробуем «родной» для системы, иначе лог заполняется
# ошибками вида «apt-get: command not found» на каждой не-Debian системе.
PKG_INSTALL = {
    "debian": "apt-get update && apt-get install -y",
    "rhel": "dnf install -y",
    "suse": "zypper --non-interactive install",
    "arch": "pacman -Sy --noconfirm",
    "alpine": "apk add --no-cache",
}

# Все менеджеры — как запасные варианты, если «родной» почему-то недоступен
# (например, os_type определён неверно или образ подменён своим).
_ALL_PKG_INSTALL = [
    "apt-get update && apt-get install -y",
    "dnf install -y",
    "yum install -y",
    "zypper --non-interactive install",
    "pacman -Sy --noconfirm",
    "apk add --no-cache",
]


def install_package_cmd_chain(os_type: str, package: str) -> str:
    """Цепочка попыток установки пакета: сначала родной менеджер, затем прочие."""
    native = PKG_INSTALL.get(family_of(os_type))
    ordered = ([native] if native else []) + [c for c in _ALL_PKG_INSTALL if c != native]
    return " || ".join(f"({cmd} {package}) && break" for cmd in ordered)


# Семейства, где брандмауэр гостя включён по умолчанию и блокирует HTTP.
#
# firewalld установлен и активен в RHEL-семействе (CentOS/Rocky/Alma/Fedora) и
# в openSUSE; в разрешённых по умолчанию службах — SSH и пара служебных, а
# порт 80 НЕ открыт. В Debian и Ubuntu брандмауэра по умолчанию нет вообще.
# Именно это и оставалось причиной «на Ubuntu сайт открывается, на остальных
# нет» уже после того, как сам шаблон начал отрабатывать: веб-сервер запущен и
# слушает :80, проброс портов с хоста настроен, а firewalld внутри гостя молча
# отбрасывает входящие пакеты.
#
# Отключаем его, а не открываем отдельные порты: доступом к ВМ управляет
# панель на уровне хоста (reconcile_vm_firewall_rules — DNAT плюс FORWARD с
# белым списком), и второй, невидимый для панели брандмауэр внутри гостя
# делает её настройки портов неправдой. Ubuntu-машины и так работают без него,
# так что это ещё и выравнивает поведение всех систем.
FIREWALL_FAMILIES = ("rhel", "suse")


def disable_guest_firewall_cmd(os_type: str) -> str:
    """Команда отключения брандмауэра гостя, либо пустая строка, если он там
    и так не используется."""
    if family_of(os_type) not in FIREWALL_FAMILIES:
        return ""
    return "systemctl disable --now firewalld 2>/dev/null || true"


# Корень сайта по умолчанию у каждого веб-сервера свой. Пути различаются не
# только между семействами, но и между Apache и nginx внутри одного: в
# RHEL-семействе Apache отдаёт /var/www/html, а nginx — /usr/share/nginx/html.
# Из-за этого страница, положенная «куда обычно», у половины систем просто не
# отдавалась, и пользователь видел заглушку дистрибутива.
APACHE_ROOT = {"debian": "/var/www/html", "rhel": "/var/www/html", "suse": "/srv/www/htdocs"}
NGINX_ROOT = {"debian": "/var/www/html", "rhel": "/usr/share/nginx/html", "suse": "/srv/www/htdocs"}


def _index_php_cmd(root: str, stack: str) -> str:
    """Кладёт минимальную страницу в корень сайта.

    Без неё Apache и nginx отдают собственную страницу-заглушку дистрибутива
    («Test Page for the HTTP Server on Fedora» и подобные) — она появляется
    ровно тогда, когда в корне нет ни одного индексного файла. Со стороны это
    неотличимо от «шаблон не сработал», хотя стек уже поднят. Заодно страница
    сразу показывает, что PHP действительно исполняется, а не отдаётся текстом.
    """
    page = (
        "<?php echo \"<h1>" + stack + " работает</h1>\";"
        " echo \"<p>PHP \" . phpversion() . \"</p>\";"
        " echo \"<p>Замените этот файл своим сайтом: " + root + "/index.php</p>\"; ?>"
    )
    return f"mkdir -p {root} && printf '%s' '{page}' > {root}/index.php"


# Конфигурация nginx для передачи .php в php-fpm.
#
# Сам по себе nginx PHP не исполняет — ему нужен явный location с fastcgi_pass,
# которого шаблон LEMP не создавал вообще: ставились nginx и php-fpm, но между
# собой они связаны не были. Путь к сокету php-fpm отличается и между
# дистрибутивами, и между версиями PHP, поэтому определяем его на месте, а не
# зашиваем: ls по обоим известным расположениям и первый найденный.
#
# Кавычки одинарные — важно: $document_root и $fastcgi_script_name должен
# подставить nginx, а не shell при записи файла.
_NGINX_PHP_LOCATION = (
    "PHPSOCK=$(ls /run/php-fpm/www.sock /run/php/php*-fpm.sock /var/run/php-fpm/www.sock "
    "2>/dev/null | head -n1); "
    "[ -n \"$PHPSOCK\" ] && printf '%s\\n' "
    "'index index.php index.html;' "
    "'location ~ \\.php$ {' "
    "'    include fastcgi_params;' "
    "\"    fastcgi_pass unix:$PHPSOCK;\" "
    "'    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;' "
    "'}' "
)


def _nginx_php_conf_cmd(family: str) -> str:
    """Команда, создающая конфиг nginx для PHP в нужном для семейства месте.

    В RHEL-семействе nginx.conf уже содержит `include /etc/nginx/default.d/*.conf`
    внутри блока server — это штатная точка расширения, и добавлять туда
    location можно, не трогая основной конфиг. В Debian такого include нет,
    поэтому дописываем в конфиг сайта по умолчанию через отдельный server-блок
    в conf.d, предварительно убрав дефолтный сайт, иначе они столкнутся на 80.
    """
    if family == "rhel":
        return _NGINX_PHP_LOCATION + "> /etc/nginx/default.d/aegis-php.conf"
    if family == "suse":
        return _NGINX_PHP_LOCATION + "> /etc/nginx/vhosts.d/aegis-php.conf"
    # debian: свой server-блок вместо дефолтного сайта
    return (
        "rm -f /etc/nginx/sites-enabled/default; "
        "PHPSOCK=$(ls /run/php/php*-fpm.sock /run/php-fpm/www.sock 2>/dev/null | head -n1); "
        "[ -n \"$PHPSOCK\" ] && printf '%s\\n' "
        "'server {' "
        "'    listen 80 default_server;' "
        "'    root /var/www/html;' "
        "'    index index.php index.html;' "
        "'    location ~ \\.php$ {' "
        "'        include snippets/fastcgi-php.conf;' "
        "\"        fastcgi_pass unix:$PHPSOCK;\" "
        "'    }' "
        "'}' "
        "> /etc/nginx/conf.d/aegis-php.conf"
    )


# Шаблоны окружения по семействам.
#   packages — что ставить
#   commands — что выполнить после установки ({svc} подставляется через
#              enable_service_cmd, чтобы не дублировать systemd/OpenRC)
#   services — какие службы включить
# Семейство отсутствует в словаре шаблона => шаблон для него не поддерживается.
TEMPLATES = {
    "lamp": {
        "label": "LAMP (Apache + PHP + MariaDB)",
        # Индексную страницу кладём после запуска Apache — см. services_first
        "services_first": True,
        "debian": {
            "packages": ["apache2", "mariadb-server", "php", "libapache2-mod-php", "php-mysql"],
            "services": ["apache2", "mariadb"],
            "commands": [
                _index_php_cmd(APACHE_ROOT["debian"], "LAMP"),
                "systemctl reload apache2 || true",
            ],
        },
        "rhel": {
            # httpd, а не apache2; php-mysqlnd, а не php-mysql; модуль php для
            # Apache в RHEL ставится вместе с php и отдельного пакета не требует.
            "packages": ["httpd", "mariadb-server", "php", "php-mysqlnd"],
            "services": ["httpd", "mariadb"],
            "commands": [
                _index_php_cmd(APACHE_ROOT["rhel"], "LAMP"),
                # SELinux: новому файлу нужен контекст httpd_sys_content_t,
                # иначе Apache ответит 403 (см. шаблон wordpress)
                "restorecon -R " + APACHE_ROOT["rhel"] + "/ 2>/dev/null || true",
                "setsebool -P httpd_can_network_connect_db on 2>/dev/null || true",
                "systemctl reload httpd || true",
            ],
        },
        "suse": {
            "packages": ["apache2", "mariadb", "php8", "apache2-mod_php8"],
            "services": ["apache2", "mariadb"],
            "commands": [
                _index_php_cmd(APACHE_ROOT["suse"], "LAMP"),
                "systemctl reload apache2 || true",
            ],
        },
    },
    "lemp": {
        "label": "LEMP (Nginx + PHP-FPM + MariaDB)",
        # php-fpm должен уже работать, когда мы ищем его сокет для конфига nginx
        "services_first": True,
        "debian": {
            "packages": ["nginx", "mariadb-server", "php-fpm", "php-mysql"],
            "services": ["nginx", "mariadb"],
            "commands": [
                "systemctl enable --now php*-fpm || systemctl enable --now php-fpm || true",
                _nginx_php_conf_cmd("debian"),
                _index_php_cmd(NGINX_ROOT["debian"], "LEMP"),
                "nginx -t && systemctl reload nginx || true",
            ],
        },
        "rhel": {
            "packages": ["nginx", "mariadb-server", "php-fpm", "php-mysqlnd"],
            "services": ["nginx", "mariadb", "php-fpm"],
            "commands": [
                _nginx_php_conf_cmd("rhel"),
                _index_php_cmd(NGINX_ROOT["rhel"], "LEMP"),
                "restorecon -R " + NGINX_ROOT["rhel"] + "/ 2>/dev/null || true",
                "setsebool -P httpd_can_network_connect_db on 2>/dev/null || true",
                "nginx -t && systemctl reload nginx || true",
            ],
        },
        "suse": {
            "packages": ["nginx", "mariadb", "php8-fpm", "php8-mysql"],
            "services": ["nginx", "mariadb", "php-fpm"],
            "commands": [
                "mkdir -p /etc/nginx/vhosts.d",
                _nginx_php_conf_cmd("suse"),
                _index_php_cmd(NGINX_ROOT["suse"], "LEMP"),
                "nginx -t && systemctl reload nginx || true",
            ],
        },
    },
    "docker": {
        "label": "Docker (Engine + Compose)",
        "debian": {
            "packages": ["docker.io", "docker-compose-v2"],
            "services": ["docker"],
            "commands": [],
        },
        "rhel": {
            # В базовых репозиториях RHEL/CentOS docker-ce нет — подключаем
            # официальный репозиторий Docker. На Fedora пакет тот же.
            "packages": [],
            "services": [],
            "commands": [
                "dnf install -y dnf-plugins-core || yum install -y yum-utils || true",
                "dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || "
                "yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || true",
                "dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin || "
                "yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin || true",
                "systemctl enable --now docker",
            ],
        },
        "suse": {
            "packages": ["docker", "docker-compose"],
            "services": ["docker"],
            "commands": [],
        },
        "arch": {
            "packages": ["docker", "docker-compose"],
            "services": ["docker"],
            "commands": [],
        },
        "alpine": {
            "packages": ["docker", "docker-cli-compose"],
            "services": ["docker"],
            "commands": [],
        },
    },
    "portainer": {
        "label": "Portainer (Docker + веб-UI :9000)",
        "_after_docker": [
            "docker volume create portainer_data",
            "docker run -d -p 9000:9000 --name portainer --restart=always "
            "-v /var/run/docker.sock:/var/run/docker.sock -v portainer_data:/data "
            "portainer/portainer-ce:latest",
        ],
    },
    "nodejs": {
        "label": "Node.js 20 LTS (+ pm2)",
        "debian": {
            "packages": [],
            "services": [],
            "commands": [
                "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
                "DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs",
                "npm install -g pm2 || true",
            ],
        },
        "rhel": {
            # nodesource-скрипт для rpm — свой; на Fedora/RHEL 9 проще
            # использовать модуль/пакет из репозитория дистрибутива.
            "packages": [],
            "services": [],
            "commands": [
                "dnf module -y enable nodejs:20 2>/dev/null || true",
                "dnf install -y nodejs npm || yum install -y nodejs npm || true",
                "npm install -g pm2 || true",
            ],
        },
        "suse": {
            "packages": ["nodejs20", "npm20"],
            "services": [],
            "commands": ["npm install -g pm2 || true"],
        },
        "arch": {
            "packages": ["nodejs", "npm"],
            "services": [],
            "commands": ["npm install -g pm2 || true"],
        },
        "alpine": {
            "packages": ["nodejs", "npm"],
            "services": [],
            "commands": ["npm install -g pm2 || true"],
        },
    },
    "python": {
        "label": "Python 3 (pip + venv + gunicorn)",
        "debian": {
            "packages": ["python3", "python3-pip", "python3-venv", "python3-dev", "build-essential"],
            "services": [],
            "commands": [
                "pip3 install --break-system-packages virtualenv gunicorn 2>/dev/null || "
                "pip3 install virtualenv gunicorn || true"
            ],
        },
        "rhel": {
            # python3-venv в RHEL нет — venv входит в стандартную библиотеку;
            # заголовки лежат в python3-devel, компилятор — в gcc.
            "packages": ["python3", "python3-pip", "python3-devel", "gcc", "make"],
            "services": [],
            "commands": ["pip3 install virtualenv gunicorn || true"],
        },
        "suse": {
            "packages": ["python3", "python3-pip", "python3-devel", "gcc", "make"],
            "services": [],
            "commands": ["pip3 install virtualenv gunicorn || true"],
        },
        "arch": {
            "packages": ["python", "python-pip", "base-devel"],
            "services": [],
            "commands": ["pip3 install --break-system-packages virtualenv gunicorn 2>/dev/null || true"],
        },
        "alpine": {
            "packages": ["python3", "py3-pip", "python3-dev", "build-base"],
            "services": [],
            "commands": ["pip3 install --break-system-packages virtualenv gunicorn 2>/dev/null || true"],
        },
    },
    "postgresql": {
        "label": "PostgreSQL сервер",
        "debian": {
            "packages": ["postgresql", "postgresql-contrib"],
            "services": ["postgresql"],
            "commands": [],
        },
        "rhel": {
            # В RHEL кластер БД не создаётся при установке пакета — без initdb
            # служба не стартует вообще.
            "packages": ["postgresql-server", "postgresql-contrib"],
            "services": ["postgresql"],
            "commands": ["postgresql-setup --initdb || /usr/bin/postgresql-setup initdb || true"],
        },
        "suse": {
            "packages": ["postgresql-server"],
            "services": ["postgresql"],
            "commands": [],
        },
        "arch": {
            "packages": ["postgresql"],
            "services": ["postgresql"],
            "commands": [
                "su - postgres -c \"initdb --locale=C.UTF-8 -D /var/lib/postgres/data\" || true"
            ],
        },
        "alpine": {
            "packages": ["postgresql"],
            "services": ["postgresql"],
            "commands": [],
        },
    },
    "redis": {
        "label": "Redis сервер",
        "debian": {
            "packages": ["redis-server"],
            "services": ["redis-server"],
            "commands": [],
        },
        "rhel": {
            "packages": ["redis"],
            "services": ["redis"],
            "commands": [],
        },
        "suse": {
            "packages": ["redis"],
            "services": ["redis"],
            "commands": [],
        },
        "arch": {
            "packages": ["redis"],
            "services": ["redis"],
            "commands": [],
        },
        "alpine": {
            "packages": ["redis"],
            "services": ["redis"],
            "commands": [],
        },
    },
    "wordpress": {
        "label": "WordPress (Apache + MariaDB + PHP)",
        # Файлы раскладываются в docroot и веб-сервер перезапускается — значит
        # он должен быть уже поднят, поэтому службы включаем до команд.
        "services_first": True,
        "debian": {
            "packages": ["apache2", "mariadb-server", "php", "php-mysql", "php-gd", "php-xml",
                         "php-mbstring", "php-curl", "wget", "tar"],
            "services": ["apache2", "mariadb"],
            "commands": [
                "wget -q https://wordpress.org/latest.tar.gz -O /tmp/wp.tar.gz",
                "tar -xzf /tmp/wp.tar.gz -C /var/www/html/ --strip-components=1",
                "chown -R www-data:www-data /var/www/html/",
                "a2enmod rewrite && systemctl restart apache2 || true",
            ],
        },
        "rhel": {
            # php-curl отдельным пакетом в RHEL нет — расширение входит в php-common
            "packages": ["httpd", "mariadb-server", "php", "php-mysqlnd", "php-gd", "php-xml",
                         "php-mbstring", "wget", "tar"],
            "services": ["httpd", "mariadb"],
            "commands": [
                "wget -q https://wordpress.org/latest.tar.gz -O /tmp/wp.tar.gz",
                "tar -xzf /tmp/wp.tar.gz -C /var/www/html/ --strip-components=1",
                # В RHEL веб-сервер работает от пользователя apache, а не www-data;
                # mod_rewrite включён в конфигурации по умолчанию, a2enmod там нет.
                "chown -R apache:apache /var/www/html/",
                # SELinux в облачных образах RHEL-семейства работает в режиме
                # enforcing. Файлы, распакованные из tar, получают контекст
                # НЕ httpd_sys_content_t, и Apache отдаёт на них ровно «403
                # Forbidden» — при полностью рабочих правах и запущенной службе.
                # restorecon возвращает файлам ожидаемый контекст.
                "restorecon -R /var/www/html/ 2>/dev/null || true",
                # PHP подключается к MariaDB; без этого булева SELinux рвёт
                # соединение веб-сервера с базой.
                "setsebool -P httpd_can_network_connect_db on 2>/dev/null || true",
                "systemctl restart httpd || true",
            ],
        },
    },
}


def template_supported(template: str, os_type: str) -> bool:
    """Поддерживается ли шаблон окружения для этой ОС."""
    if not template:
        return True
    # У ОС со своим веб-стеком запрещены только шаблоны, которые тоже поднимают
    # веб-сервер: два таких стека подерутся за порт 80 (см. WEB_STACK_TEMPLATES)
    if os_type in OS_WITH_OWN_WEB_STACK and template in WEB_STACK_TEMPLATES:
        return False
    spec = TEMPLATES.get(template)
    if not spec:
        return False
    if template == "portainer":
        # Portainer — это Docker плюс запуск контейнера, поэтому доступен везде,
        # где доступен сам Docker.
        return template_supported("docker", os_type)
    return family_of(os_type) in spec


def supported_templates_for(os_type: str) -> list:
    """Список шаблонов, применимых к данной ОС (для интерфейса)."""
    return [name for name in TEMPLATES if template_supported(name, os_type)]


def build_template_steps(template: str, os_type: str):
    """Возвращает (packages, commands) для шаблона под конкретную ОС.

    Пустой шаблон или неподдерживаемая пара — пустые списки: вызывающий код
    должен был отклонить такую комбинацию раньше (см. template_supported).
    """
    if not template or not template_supported(template, os_type):
        return [], []

    family = family_of(os_type)

    if template == "portainer":
        packages, commands = build_template_steps("docker", os_type)
        return packages, commands + TEMPLATES["portainer"]["_after_docker"]

    spec = TEMPLATES[template][family]
    packages = list(spec["packages"])
    commands = list(spec["commands"])
    services = [enable_service_cmd(os_type, svc) for svc in spec["services"]]

    # Порядок «службы или команды первыми» у шаблонов разный, и обе стороны
    # обязательны. postgresql в RHEL нужно сначала проинициализировать (initdb)
    # — до этого служба не стартует вообще, поэтому по умолчанию команды идут
    # первыми. А wordpress наоборот: он раскладывает файлы в docroot и делает
    # restart веб-сервера, то есть требует уже поднятой службы (иначе restart
    # шёл раньше самого enable — работало случайно, потому что restart умеет
    # запустить остановленную службу).
    if TEMPLATES[template].get("services_first"):
        return packages, services + commands
    return packages, commands + services


# Имя пакета NFS-клиента: нужен, когда к ВМ подключают сетевые диски.
NFS_CLIENT_PACKAGE = {
    "debian": "nfs-common",
    "rhel": "nfs-utils",
    "suse": "nfs-client",
    "arch": "nfs-utils",
    "alpine": "nfs-utils",
}


def nfs_client_package(os_type: str) -> str:
    return NFS_CLIENT_PACKAGE.get(family_of(os_type), "nfs-common")
