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
WEB_STACK_TEMPLATES = ("lamp", "lemp", "wordpress", "zabbix")

# Точечные запреты «шаблон × конкретная ОС» — когда семейства недостаточно.
#
# Zabbix ставится из официального репозитория Zabbix SIA, а тот собран под
# конкретные релизы: rhel/8, rhel/9, ubuntu24.04, debian12 и т.п. Адрес
# репозитория собирается в госте из VERSION_ID (см. ZABBIX_REPO_CMD), и для
# Fedora это ломается принципиально: у неё VERSION_ID вида «41», а репозитория
# «el41» не существует. Собственных пакетов Zabbix в репозиториях Fedora тоже
# нет, а подсовывать ей сборку под RHEL — гарантированный конфликт версий PHP
# и библиотек. Честнее не предлагать шаблон вовсе, чем дать ему провалиться
# на этапе установки.
TEMPLATE_OS_EXCLUSIONS = {
    "zabbix": ("fedora",),
}


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


# Сколько раз повторять установку пакетов, прежде чем сдаться. Столько же, что
# у qemu-guest-agent (см. cloudinit.guest_agent_runcmd): причина повторов та же
# — занятый dpkg-лок от unattended-upgrades сразу после загрузки и не до конца
# поднявшаяся сеть.
PACKAGE_INSTALL_RETRIES = 30


def install_packages_runcmd(os_type: str, packages) -> str:
    """Установка списка пакетов ОДНОЙ строкой runcmd, с повторами.

    Зачем не декларативный `packages:` в cloud-config: этот модуль
    (package-update-upgrade-install) выполняется на стадии CONFIG, а runcmd —
    на стадии FINAL, то есть заведомо позже. Ограниченное ожидание сети
    (WAIT_NETWORK_RUNCMD) живёт в runcmd, поэтому защитить `packages:` оно не
    может физически: к моменту его запуска пакеты уже пытались (и не смогли)
    поставиться.

    Симптом на живом сервере: ВМ поднималась, SSH работал, а окружения не было
    вообще — ни mariadb у Zabbix, ни docker у приложений маркетплейса, причём
    без единой ошибки в панели. Дальше валилось всё, что от них зависит:
    `systemctl enable --now mariadb` не находил юнит, `docker compose up` —
    команду docker.

    Возвращает пустую строку, если ставить нечего.
    """
    pkgs = [p for p in (packages or []) if p]
    if not pkgs:
        return ""
    joined = " ".join(pkgs)
    chain = install_package_cmd_chain(os_type, joined)
    return (f"i=1; while [ $i -le {PACKAGE_INSTALL_RETRIES} ]; do "
            f"{chain} || sleep 5; i=$((i+1)); done || true")


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


# Сокет php-fpm под нашим собственным, фиксированным именем — вместо того,
# чтобы угадывать, куда упаковщик дистрибутива положил его по умолчанию (это
# отличается и между дистрибутивами, и между версиями PHP: /run/php/phpX.Y-fpm.sock,
# /run/php-fpm/www.sock и т.д.). Хуже того — на openSUSE пул www по умолчанию
# вообще слушает не unix-сокет, а TCP 127.0.0.1:9000, и поиск *.sock не нашёл
# бы там вообще ничего.
#
# Вместо угадывания сами переписываем listen-директиву пула на этот путь
# (см. _pin_php_fpm_socket_cmd) и здесь же на него ссылаемся — эта часть
# больше ничего не ищет и не может «не найти» сокет.
AEGIS_PHP_FPM_SOCK = "/run/aegis-php-fpm.sock"

# Файл пула php-fpm по умолчанию (www.conf) под каждое семейство — только для
# того, чтобы переписать в нём listen. Различаются оба уровня пути: и каталог
# конфигурации (/etc/php vs /etc/php-fpm.d vs /etc/php8/fpm), и то, что там
# может быть НЕСКОЛЬКО версий PHP разом (Debian) — отсюда маска, а не имя файла.
PHP_FPM_POOL_CONF_GLOB = {
    "debian": "/etc/php/*/fpm/pool.d/www.conf",
    "rhel": "/etc/php-fpm.d/www.conf",
    "suse": "/etc/php8/fpm/pool.d/www.conf",
}


def _pin_php_fpm_socket_cmd(family: str) -> str:
    """Переписывает listen-директиву пула php-fpm на AEGIS_PHP_FPM_SOCK."""
    conf_glob = PHP_FPM_POOL_CONF_GLOB.get(family)
    if not conf_glob:
        return ""
    return (
        f"for f in {conf_glob}; do [ -f \"$f\" ] && "
        f"sed -i 's#^listen = .*#listen = {AEGIS_PHP_FPM_SOCK}#' \"$f\"; done"
    )


def _php_fpm_systemctl_cmd(family: str, action: str) -> str:
    """`systemctl <action>` над настоящим именем юнита php-fpm.

    В Debian/Ubuntu юнит версионирован (php8.3-fpm.service) и меняется от
    релиза к релизу — простой `systemctl <action> php-fpm` там не сработает.
    `systemctl list-unit-files PATTERN` матчит по glob-маске сам, штатно —
    в отличие от передачи маски аргументом в systemctl напрямую, которую
    сначала попытался бы развернуть сам bash по файлам текущего каталога."""
    if family == "debian":
        return (
            f"systemctl {action} "
            "$(systemctl list-unit-files 'php*-fpm.service' --no-legend | awk '{print $1}' | head -n1) "
            f"2>/dev/null || systemctl {action} php-fpm 2>/dev/null || true"
        )
    return f"systemctl {action} php-fpm 2>/dev/null || true"


def _enable_php_fpm_cmd(family: str) -> str:
    return _php_fpm_systemctl_cmd(family, "enable --now")


def _restart_php_fpm_cmd(family: str) -> str:
    return _php_fpm_systemctl_cmd(family, "restart")


def _nginx_php_conf_cmd(family: str) -> str:
    """Команда, создающая конфиг nginx для PHP в нужном для семейства месте.

    В RHEL-семействе nginx.conf уже содержит `include /etc/nginx/default.d/*.conf`
    внутри блока server — это штатная точка расширения, и добавлять туда
    location можно, не трогая основной конфиг. В openSUSE аналогичный
    include есть для vhosts.d. В Debian такого include нет, поэтому дописываем
    в конфиг сайта по умолчанию через отдельный server-блок в conf.d,
    предварительно убрав дефолтный сайт, иначе они столкнутся на 80.
    """
    location = (
        "printf '%s\\n' "
        "'index index.php index.html;' "
        "'location ~ \\.php$ {' "
        "'    include fastcgi_params;' "
        f"'    fastcgi_pass unix:{AEGIS_PHP_FPM_SOCK};' "
        "'    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;' "
        "'}' "
    )
    if family == "rhel":
        return location + "> /etc/nginx/default.d/aegis-php.conf"
    if family == "suse":
        return location + "> /etc/nginx/vhosts.d/aegis-php.conf"
    # debian: свой server-блок вместо дефолтного сайта
    return (
        "rm -f /etc/nginx/sites-enabled/default; "
        "printf '%s\\n' "
        "'server {' "
        "'    listen 80 default_server;' "
        "'    root /var/www/html;' "
        "'    index index.php index.html;' "
        "'    location ~ \\.php$ {' "
        f"'        fastcgi_pass unix:{AEGIS_PHP_FPM_SOCK};' "
        "'        include fastcgi_params;' "
        "'        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;' "
        "'    }' "
        "'}' "
        "> /etc/nginx/conf.d/aegis-php.conf"
    )


# openSUSE Leap 15.6's standard OSS repo does not include PHP 8 at all — it
# lives in the devel:languages:php project repo and has to be added
# explicitly. cloud-init's `packages:` module installs everything in ONE
# zypper transaction; one unresolvable package name fails the whole
# transaction, so nginx/mariadb — which ARE in the standard repo — never got
# installed either. The VM booted, networking worked (see build_network_data),
# and nothing answered on port 80 at all: indistinguishable from "didn't
# start". PHP packages for suse are therefore installed via runcmd, after this
# repo is registered, instead of sitting in the declarative `packages:` list.
SUSE_PHP_REPO_CMD = (
    "(zypper --non-interactive ar --no-refresh "
    "https://download.opensuse.org/repositories/devel:languages:php/openSUSE_Leap_15.6/ "
    "aegis-php || true) && "
    "zypper --non-interactive --gpg-auto-import-keys refresh aegis-php 2>/dev/null || true"
)


# --------------------------------------------------------------------------
# Zabbix
#
# Ставится из официального репозитория Zabbix SIA (в штатных репозиториях
# дистрибутивов Zabbix-сервера нет). Репозиторий собран под КОНКРЕТНЫЕ релизы,
# поэтому адрес собирается уже в госте из /etc/os-release, а не зашивается:
# ubuntu24.04, debian12, rhel/9 и т.д. Проверено, что схема с «latest» в имени
# существует для Ubuntu 22.04/24.04, Debian 11/12/13 и RHEL 8/9 — это избавляет
# от угадывания номера сборки пакета, который меняется от релиза к релизу.
#
# Веб-мастер первичной настройки не нужен: если заранее положить готовый
# /etc/zabbix/web/zabbix.conf.php, фронтенд видит настроенное подключение и
# сразу открывает рабочую панель. Пароль к БД генерируется в самом госте
# (в статическом шаблоне взяться ему неоткуда) и переиспользуется из файла с
# правами 600 — каждая команда runcmd выполняется отдельным процессом, поэтому
# переменные между ними не живут.
ZABBIX_VERSION = "7.0"          # текущая LTS: поддержка до 2029 года
WP_DB_PASS_FILE = "/root/.aegis_wp_db_pass"


def _wordpress_db_steps(web_user: str) -> list:
    """База, пользователь и wp-config.php для WordPress.

    Без этих шагов шаблон разворачивал Apache, MariaDB и файлы WordPress — но
    ни базы, ни wp-config.php не создавал. Мастер установки при первом
    открытии просил реквизиты БД, которых не существует, и пройти его было
    нельзя: шаблон выглядел рабочим, а сайт поднять было невозможно.

    Пароль генерируется в файл с правами 600 (как у Zabbix, см.
    _zabbix_common_steps), а не подставляется в cloud-init: тот остаётся в
    логах и в метаданных ВМ.
    """
    p = WP_DB_PASS_FILE
    return [
        f"install -m 600 /dev/null {p} && openssl rand -hex 16 > {p}",
        f"P=$(cat {p}); mysql -uroot -e \"create database if not exists wordpress "
        "character set utf8mb4 collate utf8mb4_unicode_ci; "
        "create user if not exists wordpress@localhost identified by '$P'; "
        "grant all privileges on wordpress.* to wordpress@localhost; flush privileges;\"",
        # -n: при повторном запуске cloud-init не затираем уже настроенный конфиг
        "cp -n /var/www/html/wp-config-sample.php /var/www/html/wp-config.php",
        f"P=$(cat {p}); sed -i \"s/database_name_here/wordpress/; s/username_here/wordpress/; "
        "s/password_here/$P/\" /var/www/html/wp-config.php",
        # Соли по умолчанию одинаковы во всех установках — генерируем свои.
        # Разделитель | вместо /, т.к. base64 может содержать слеши (их же и
        # вырезаем), а & в base64 не встречается и sed его не подменит.
        "for k in AUTH_KEY SECURE_AUTH_KEY LOGGED_IN_KEY NONCE_KEY AUTH_SALT "
        "SECURE_AUTH_SALT LOGGED_IN_SALT NONCE_SALT; do "
        "S=$(openssl rand -base64 48 | tr -d '\\n/'); "
        "sed -i \"s|define( *'$k'.*|define('$k', '$S');|\" /var/www/html/wp-config.php; done",
        f"chown {web_user}:{web_user} /var/www/html/wp-config.php && "
        "chmod 640 /var/www/html/wp-config.php",
    ]


ZABBIX_DB_PASS_FILE = "/root/.aegis_zabbix_db_pass"

# Адрес хоста со стороны ВМ: мост br-vms поднимается инсталлятором с
# 172.20.0.1/24 и раздаёт его же как шлюз (см. install.sh). Именно по нему
# гость достаёт службы самой панели — в частности почтовый сервер.
AEGIS_BRIDGE_GATEWAY = "172.20.0.1"

# Строки конфигурации фронтенда. Пароль подставляется отдельным шагом (sed),
# чтобы не смешивать одинарные кавычки shell с кавычками PHP.
_ZABBIX_WEB_CONF_LINES = (
    "'<?php' "
    "'$DB[\"TYPE\"] = \"MYSQL\";' "
    "'$DB[\"SERVER\"] = \"localhost\";' "
    "'$DB[\"PORT\"] = \"0\";' "
    "'$DB[\"DATABASE\"] = \"zabbix\";' "
    "'$DB[\"USER\"] = \"zabbix\";' "
    "'$DB[\"PASSWORD\"] = \"__AEGIS_ZBX_PASS__\";' "
    "'$DB[\"SCHEMA\"] = \"\";' "
    "'$DB[\"ENCRYPTION\"] = false;' "
    "'$DB[\"VERIFY_HOST\"] = false;' "
    "'$DB[\"DOUBLE_IEEE754\"] = true;' "
    "'$ZBX_SERVER = \"localhost\";' "
    "'$ZBX_SERVER_PORT = \"10051\";' "
    "'$ZBX_SERVER_NAME = \"Aegis\";' "
    "'$IMAGE_FORMAT_DEFAULT = IMAGE_FORMAT_PNG;' "
)


def _zabbix_common_steps(web_user: str, web_service: str) -> list:
    """Шаги, одинаковые для всех семейств: база, схема, конфиги, запуск."""
    p = ZABBIX_DB_PASS_FILE
    return [
        # Пароль БД: создаём файл сразу с правами 600, а не chmod после записи —
        # иначе между записью и chmod он на мгновение читаем всем.
        f"install -m 600 /dev/null {p} && openssl rand -hex 16 > {p}",
        # log_bin_trust_function_creators нужен на время импорта схемы: она
        # создаёт хранимые функции, а при включённом бинарном логе MariaDB это
        # запрещает.
        f"P=$(cat {p}); mysql -uroot -e \"create database if not exists zabbix "
        "character set utf8mb4 collate utf8mb4_bin; "
        "create user if not exists zabbix@localhost identified by '$P'; "
        "grant all privileges on zabbix.* to zabbix@localhost; "
        'set global log_bin_trust_function_creators = 1;"',
        f"P=$(cat {p}); zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz "
        '| mysql --default-character-set=utf8mb4 -uzabbix -p"$P" zabbix',
        'mysql -uroot -e "set global log_bin_trust_function_creators = 0;" || true',
        # Почтовый канал: направляем на почтовый сервер самой панели, иначе
        # оповещения некуда слать и штатный канал остаётся выключенным с
        # заглушкой mail.example.com.
        #
        # Сетевой путь уже открыт: почтовый сервер публикует 25/587 на хосте, а
        # блокировка доступа ВМ к хосту закрывает только порты панели и её
        # инфраструктуры (5432, 5672, 15672, 8000, 8001) — SMTP среди них нет.
        #
        # Условие smtp_server='mail.example.com' попадает ровно в два штатных
        # канала («Email» и «Email (HTML)»), которые Zabbix поставляет с этой
        # заглушкой, и не задевает Gmail/Office365 — у тех прописаны настоящие
        # серверы. status=0 — включён (по умолчанию у media_type status=1,
        # то есть выключен).
        'mysql -uroot -e "update zabbix.media_type set '
        f"smtp_server='{AEGIS_BRIDGE_GATEWAY}', smtp_port=25, "
        "smtp_helo='aegis.local', smtp_email='zabbix@aegis.local', status=0 "
        "where type=0 and smtp_server='mail.example.com';\" || true",
        # Пароль в конфиг сервера: строка в поставляемом файле закомментирована,
        # поэтому сначала пробуем раскомментировать, а если её нет — дописываем.
        f"P=$(cat {p}); sed -i \"s|^# *DBPassword=.*|DBPassword=$P|\" "
        "/etc/zabbix/zabbix_server.conf; "
        "grep -q '^DBPassword=' /etc/zabbix/zabbix_server.conf || "
        'echo "DBPassword=$P" >> /etc/zabbix/zabbix_server.conf',
        # Готовый конфиг фронтенда — именно он отменяет веб-мастер установки.
        "mkdir -p /etc/zabbix/web && printf '%s\\n' " + _ZABBIX_WEB_CONF_LINES
        + "> /etc/zabbix/web/zabbix.conf.php",
        f"P=$(cat {p}); sed -i \"s|__AEGIS_ZBX_PASS__|$P|\" "
        f"/etc/zabbix/web/zabbix.conf.php && chown {web_user}:{web_user} "
        "/etc/zabbix/web/zabbix.conf.php && chmod 640 /etc/zabbix/web/zabbix.conf.php",
        f"systemctl enable --now zabbix-server zabbix-agent {web_service} || true",
        f"systemctl restart zabbix-server zabbix-agent {web_service} || true",
    ]


# zabbix-get и zabbix-sender — консольные утилиты: проверить элемент данных и
# отправить значение вручную прямо из терминала панели, не открывая браузер.
_ZABBIX_PACKAGES = ("zabbix-server-mysql zabbix-sql-scripts zabbix-agent "
                    "zabbix-get zabbix-sender")

ZABBIX_STEPS_DEBIAN = [
    # ID и VERSION_ID из /etc/os-release дают ровно то, что ждёт репозиторий:
    # ubuntu + 24.04 -> ubuntu24.04, debian + 12 -> debian12.
    ". /etc/os-release && cd /tmp && "
    f"curl -fsSLO https://repo.zabbix.com/zabbix/{ZABBIX_VERSION}/"
    "${ID}/pool/main/z/zabbix-release/zabbix-release_latest+${ID}${VERSION_ID}_all.deb && "
    "dpkg -i zabbix-release_latest+${ID}${VERSION_ID}_all.deb && apt-get update",
    "DEBIAN_FRONTEND=noninteractive apt-get install -y "
    f"{_ZABBIX_PACKAGES} zabbix-frontend-php zabbix-apache-conf",
] + _zabbix_common_steps(web_user="www-data", web_service="apache2")

ZABBIX_STEPS_RHEL = [
    # VERSION_ID у AlmaLinux/Rocky бывает вида «9.4» — репозиторию нужен только
    # мажорный номер, отсюда ${VERSION_ID%%.*}.
    '. /etc/os-release && V=${VERSION_ID%%.*} && rpm -Uvh --replacepkgs '
    f"https://repo.zabbix.com/zabbix/{ZABBIX_VERSION}/rhel/$V/x86_64/"
    f"zabbix-release-latest-{ZABBIX_VERSION}.el$V.noarch.rpm && dnf clean all",
    "dnf install -y "
    f"{_ZABBIX_PACKAGES} zabbix-web-mysql zabbix-apache-conf",
    # SELinux в облачных образах RHEL работает в режиме enforcing: без этих
    # булевых веб-интерфейс не достучится ни до базы, ни до zabbix-server и
    # отдаст пустую страницу либо ошибку подключения.
    "setsebool -P httpd_can_network_connect_db on 2>/dev/null || true",
    "setsebool -P httpd_can_connect_zabbix on 2>/dev/null || true",
] + _zabbix_common_steps(web_user="apache", web_service="httpd")


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
            # php8/apache2-mod_php8 НЕТ в стандартном OSS-репозитории Leap
            # 15.6 — этих пакетов не будет здесь, они ставятся ниже, после
            # подключения репозитория. Иначе одна нерезолвящаяся зависимость
            # рвёт всю транзакцию zypper целиком, и apache2 с mariadb (они-то
            # как раз в стандартном репозитории) тоже не устанавливаются —
            # ВМ поднимается пустой, будто шаблон вообще не запускался.
            "packages": ["apache2", "mariadb"],
            "services": ["apache2", "mariadb"],
            "commands": [
                SUSE_PHP_REPO_CMD,
                "zypper --non-interactive install php8 apache2-mod_php8 || true",
                _index_php_cmd(APACHE_ROOT["suse"], "LAMP"),
                "systemctl reload apache2 || true",
            ],
        },
    },
    "lemp": {
        "label": "LEMP (Nginx + PHP-FPM + MariaDB)",
        # php-fpm должен уже работать, когда мы переписываем его сокет и пишем
        # конфиг nginx на него
        "services_first": True,
        "debian": {
            "packages": ["nginx", "mariadb-server", "php-fpm", "php-mysql"],
            "services": ["nginx", "mariadb"],
            "commands": [
                _enable_php_fpm_cmd("debian"),
                _pin_php_fpm_socket_cmd("debian"),
                _restart_php_fpm_cmd("debian"),
                _nginx_php_conf_cmd("debian"),
                _index_php_cmd(NGINX_ROOT["debian"], "LEMP"),
                "nginx -t && systemctl reload nginx || true",
            ],
        },
        "rhel": {
            "packages": ["nginx", "mariadb-server", "php-fpm", "php-mysqlnd"],
            "services": ["nginx", "mariadb", "php-fpm"],
            "commands": [
                _pin_php_fpm_socket_cmd("rhel"),
                _restart_php_fpm_cmd("rhel"),
                _nginx_php_conf_cmd("rhel"),
                _index_php_cmd(NGINX_ROOT["rhel"], "LEMP"),
                "restorecon -R " + NGINX_ROOT["rhel"] + "/ 2>/dev/null || true",
                "setsebool -P httpd_can_network_connect_db on 2>/dev/null || true",
                "nginx -t && systemctl reload nginx || true",
            ],
        },
        "suse": {
            # php8-fpm/php8-mysql — та же история, что и в LAMP: их нет в
            # стандартном репозитории Leap 15.6, ставим отдельно после
            # подключения репозитория (см. SUSE_PHP_REPO_CMD). php-fpm поэтому
            # убран и из декларативного "services" — юнит не существует до
            # явной установки ниже.
            "packages": ["nginx", "mariadb"],
            "services": ["nginx", "mariadb"],
            "commands": [
                "mkdir -p /etc/nginx/vhosts.d",
                SUSE_PHP_REPO_CMD,
                "zypper --non-interactive install php8-fpm php8-mysql || true",
                _enable_php_fpm_cmd("suse"),
                _pin_php_fpm_socket_cmd("suse"),
                _restart_php_fpm_cmd("suse"),
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
            # docker-compose есть в Leap не в каждом релизе, поэтому в
            # атомарном "packages" ему не место: cloud-init ставит весь
            # список одной транзакцией zypper, и одно неразрешимое имя
            # провалило бы её целиком — вместе с самим docker. Ровно так уже
            # ломался LAMP на openSUSE из-за php8. Compose ставим отдельно и
            # необязательно: без него Docker всё равно работает.
            "packages": ["docker"],
            "services": ["docker"],
            "commands": [
                "zypper --non-interactive install docker-compose "
                "|| zypper --non-interactive install docker-compose-switch || true",
            ],
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
        "port": 9000,
        "_after_docker": [
            "docker volume create portainer_data",
            "docker run -d -p 9000:9000 --name portainer --restart=always "
            "-v /var/run/docker.sock:/var/run/docker.sock -v portainer_data:/data "
            "portainer/portainer-ce:latest",
        ],
    },
    "grafana": {
        "label": "Grafana (дашборды и графики :3000)",
        "port": 3000,
        # Как и Portainer, ставится контейнером поверх Docker (см. _after_docker
        # в build_template_steps) — своих пакетов в репозиториях дистрибутивов
        # у Grafana либо нет, либо они сильно отстают от upstream.
        "_after_docker": [
            "docker volume create grafana_data",
            # GF_SECURITY_ADMIN_PASSWORD не задаём: при первом входе Grafana
            # сама потребует сменить дефолтный admin/admin, и пароль не
            # окажется ни в логе cloud-init, ни в истории команд.
            "docker run -d -p 3000:3000 --name grafana --restart=always "
            "-v grafana_data:/var/lib/grafana "
            "grafana/grafana-oss:latest",
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
            # Fedora 41+ заменила Redis на Valkey (Redis сменил лицензию на
            # SSPL, несовместимую с политикой Fedora). `dnf install redis`
            # по-прежнему работает и ставит valkey-compat — команды
            # redis-cli/redis-server на месте, — но ЮНИТ называется
            # valkey.service. Поэтому имя службы не угадываем, а пробуем оба:
            # на AlmaLinux/Rocky/CentOS это по-прежнему redis.
            "packages": ["redis"],
            "services": [],
            "commands": [
                "systemctl enable --now redis 2>/dev/null "
                "|| systemctl enable --now valkey 2>/dev/null || true",
            ],
        },
        "suse": {
            # В openSUSE redis собран на ШАБЛОННЫХ юнитах (redis@<экземпляр>),
            # и без конфига не стартует вообще: сначала нужно сделать
            # default.conf из поставляемого примера. Простой
            # `systemctl enable --now redis` там не делает ничего.
            "packages": ["redis"],
            "services": [],
            "commands": [
                "[ -f /etc/redis/default.conf ] || cp /etc/redis/default.conf.example "
                "/etc/redis/default.conf 2>/dev/null || true",
                "chown redis:redis /etc/redis/default.conf 2>/dev/null || true",
                "systemctl enable --now redis@default 2>/dev/null "
                "|| systemctl enable --now redis 2>/dev/null || true",
            ],
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
            ] + _wordpress_db_steps("www-data") + [
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
            ] + _wordpress_db_steps("apache") + [
                # wp-config.php создан ПОСЛЕ первого restorecon выше, поэтому
                # контекст ему нужно восстановить отдельно — иначе SELinux не
                # даст Apache прочитать конфиг, и сайт отдаст 403.
                "restorecon /var/www/html/wp-config.php 2>/dev/null || true",
                "systemctl restart httpd || true",
            ],
        },
    },
    "zabbix": {
        "label": "Zabbix (мониторинг, веб-интерфейс /zabbix)",
        # Веб-интерфейс раскладывается по docroot и требует уже поднятого
        # Apache и MariaDB, поэтому службы включаются до команд.
        "services_first": True,
        "debian": {
            # Здесь только то, что есть в штатных репозиториях дистрибутива.
            # Пакеты самого Zabbix живут во ВНЕШНЕМ репозитории и ставятся
            # ниже, отдельной командой: cloud-init выполняет весь список
            # packages одной транзакцией apt, и любое имя, которого ещё нет в
            # индексе, провалило бы установку целиком — вместе с mariadb.
            "packages": ["mariadb-server", "curl"],
            "services": ["mariadb"],
            "commands": ZABBIX_STEPS_DEBIAN,
        },
        "rhel": {
            "packages": ["mariadb-server", "curl"],
            "services": ["mariadb"],
            "commands": ZABBIX_STEPS_RHEL,
        },
    },
}


def template_supported(template: str, os_type: str) -> bool:
    """Поддерживается ли шаблон окружения для этой ОС — технически.

    Отвечает на вопрос «соберётся ли», а не «предлагаем ли»: что показывать в
    интерфейсе, решает template_offered (см. ниже).
    """
    if not template:
        return True
    # У ОС со своим веб-стеком запрещены только шаблоны, которые тоже поднимают
    # веб-сервер: два таких стека подерутся за порт 80 (см. WEB_STACK_TEMPLATES)
    if os_type in OS_WITH_OWN_WEB_STACK and template in WEB_STACK_TEMPLATES:
        return False
    # Точечные исключения, которые не выражаются через семейство (см.
    # TEMPLATE_OS_EXCLUSIONS — например, Zabbix на Fedora)
    if os_type in TEMPLATE_OS_EXCLUSIONS.get(template, ()):
        return False
    spec = TEMPLATES.get(template)
    if not spec:
        return False
    if "_after_docker" in spec:
        # Portainer и Grafana — это Docker плюс запуск контейнера, поэтому
        # доступны везде, где доступен сам Docker.
        return template_supported("docker", os_type)
    return family_of(os_type) in spec


# ОС, для которых шаблоны окружения предлагаются в интерфейсе.
#
# Технически они собираются и на остальных семействах (весь набор пакетов и
# служб под rhel/suse/arch/alpine выше — рабочий и покрыт тестами), но
# поддерживать вживую десяток дистрибутивов в каждом шаблоне слишком дорого:
# репозитории разъезжаются, имена пакетов меняются, и проверить каждую пару
# «шаблон × ОС» на живом сервере нереально. Поэтому предлагаем шаблоны там,
# где они действительно проверены, — на Ubuntu; для остальных ОС список пуст,
# и это видно сразу, а не после провалившейся установки.
TEMPLATE_OFFERED_OS = ("ubuntu",)


def template_offered(template: str, os_type: str) -> bool:
    """Предлагать ли шаблон для этой ОС в интерфейсе."""
    if not template:
        return True
    if os_type not in TEMPLATE_OFFERED_OS:
        return False
    return template_supported(template, os_type)


def supported_templates_for(os_type: str) -> list:
    """Список шаблонов, предлагаемых для данной ОС (для интерфейса)."""
    return [name for name in TEMPLATES if template_offered(name, os_type)]


def build_template_steps(template: str, os_type: str):
    """Возвращает (packages, commands) для шаблона под конкретную ОС.

    Пустой шаблон или неподдерживаемая пара — пустые списки: вызывающий код
    должен был отклонить такую комбинацию раньше (см. template_supported).
    """
    if not template or not template_supported(template, os_type):
        return [], []

    family = family_of(os_type)

    spec_all = TEMPLATES[template]
    if "_after_docker" in spec_all:
        # Portainer, Grafana: сам Docker плюс запуск контейнера поверх него.
        packages, commands = build_template_steps("docker", os_type)
        return packages, commands + spec_all["_after_docker"]

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


def template_port(template: str):
    """Порт, на котором слушает сервис шаблона, если он НЕ 80.

    Порты по умолчанию у ВМ — 22, 80 и 443. Portainer слушает 9000, Grafana —
    3000, и без этой подсказки они оставались вообще без проброса: сервис
    внутри ВМ работает, а снаружи его не достать. Именно так выглядело
    «некоторые шаблоны не работают».

    None — значит специального порта нет: либо сервис и так на 80 (lamp, lemp,
    wordpress, zabbix), либо шаблон вообще не поднимает веб-сервис (docker,
    nodejs, python) и порт задаёт уже само приложение пользователя.
    """
    spec = TEMPLATES.get(template) or {}
    return spec.get("port")
