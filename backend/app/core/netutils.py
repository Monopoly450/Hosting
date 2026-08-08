"""Единая логика определения «внутренних» IP-адресов ВМ.

Раньше k8s_client и databases фильтровали адреса по-разному, из-за чего
внешний SSH-порт мог вычисляться от служебного/эфемерного адреса и «плавал»
при каждой перезагрузке. Теперь оба места используют эти функции.
"""

# Служебные подсети, которые нельзя показывать как «внешний» адрес ВМ:
#   10.244. / 10.42.  — pod-сети Kubernetes (Calico / flannel в k3s)
#   10.0.2.           — внутренняя masquerade-сеть KubeVirt
#   127.              — loopback
#   192.168.100.      — изолированная сеть кластера (одна и та же подсеть у
#                       ВСЕХ кластеров, поэтому с хоста она неоднозначна —
#                       проброс должен идти на Pod IP; см. коммит 135746d)
#   172.17.–172.19., 172.21.–172.31. — мосты Docker ВНУТРИ гостя
#
# Про Docker-мосты подробнее — это был живой баг. Как только в ВМ ставился
# Docker (шаблон docker/portainer/grafana или любое приложение маркетплейса),
# внутри неё появлялся docker0 с адресом 172.17.0.1. qemu-guest-agent честно
# сообщал его наравне с остальными, а здесь он не отсеивался — панель
# показывала 172.17.0.1 как адрес ВМ, и туда же уходил DNAT проброса портов.
# На хосте 172.17.0.1 — это его собственный docker0, поэтому трафик уходил в
# никуда: сайт не открывался, а SSH по проброшенному порту рвал соединение.
#
# ВАЖНО: 172.20. в этот список НЕ входит — это наш собственный мост br-vms
# (см. install.sh), настоящий адрес обычных ВМ. Docker по умолчанию раздаёт
# сети из 172.17–172.31, поэтому исключаем весь диапазон КРОМЕ 172.20.
INTERNAL_IP_PREFIXES = (
    "10.244.", "10.42.", "10.0.2.", "127.", "192.168.100.",
) + tuple(f"172.{octet}." for octet in range(17, 32) if octet != 20)


def detect_host_ip() -> str:
    """IP хоста, по которому до него достучатся снаружи.

    Единая точка правды: раньше это дублировалось в vms.py (с автоопределением)
    и в деплоях/реестре/доменах/маркетплейсе (где по умолчанию возвращался
    127.0.0.1). Из-за этого проверка DNS у доменов не могла пройти никогда,
    а приложения маркетплейса получали ссылки на localhost.
    """
    import os
    import socket as _socket

    env_host = os.getenv("AEGIS_HOST_IP") or os.getenv("HOST_IP")
    if env_host:
        return env_host.strip()
    try:
        # Не отправляет пакетов — просто узнаёт, с какого адреса пошёл бы трафик.
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "172.20.0.1"


def host_for_links(request=None) -> str:
    """Адрес сервера для ссылок и команд, которые увидит пользователь.

    Берётся из того, как клиент обратился к панели, а не из общей настройки.
    Одного правильного значения не существует: домены и Let's Encrypt требуют
    публичный адрес (AEGIS_HOST_IP), но по нему из локальной сети часто не
    пройти — NAT-петля поддерживается далеко не везде. Поэтому если панель
    открыта по 192.168.x, то и ссылки, и адрес docker push должны быть
    локальными, а если по домену — на домен.

    Без запроса (фоновые задачи, воркер) остаётся detect_host_ip().
    """
    if request is not None:
        # X-Forwarded-Host важен: панель отдаётся через nginx
        forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        candidate = forwarded.split(":")[0] or request.url.hostname
        if candidate and candidate not in ("localhost", "127.0.0.1", "::1"):
            return candidate
    return detect_host_ip()


def is_internal_ip(ip: str) -> bool:
    """True, если адрес служебный (или IPv6) и не годится как внешний адрес ВМ."""
    if not ip or ":" in ip:
        return True
    return any(ip.startswith(prefix) for prefix in INTERNAL_IP_PREFIXES)


def pick_external_ip(ips):
    """Выбирает «внешний» IPv4 ВМ из списка. Приоритет — не служебному адресу;
    если такого нет, берётся первый не-IPv6; иначе — первый из списка."""
    if not ips:
        return None
    # 1. Сначала ищем настоящий внешний IP (не 10.42, 10.244, 10.0.2, 127)
    for ip in ips:
        if not is_internal_ip(ip):
            return ip
    # 2. Если все IP внутренние, предпочитаем K8s Pod IP (10.42 или 10.244), т.к. он маршрутизируется с хоста
    for ip in ips:
        if (ip.startswith("10.42.") or ip.startswith("10.244.")) and ":" not in ip:
            return ip
    # 3. Первый не-IPv6
    for ip in ips:
        if ":" not in ip:
            return ip
    return ips[0]


import re as _re

# Строгая валидация для значений, которые подставляются в shell-команды
# (iptables, nginx). Защита от инъекции команд.
_IPV4_RE = _re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
_SAFE_NAME_RE = _re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def is_valid_ipv4(value: str) -> bool:
    """True, если строка — корректный IPv4-адрес (0-255 в каждом октете)."""
    if not isinstance(value, str):
        return False
    m = _IPV4_RE.match(value)
    if not m:
        return False
    return all(0 <= int(o) <= 255 for o in m.groups())


def is_valid_ip_or_cidr(value: str) -> bool:
    """True для IPv4 или IPv4/CIDR (например, 10.0.0.0/8). Используется для
    белых списков файрвола, попадающих в iptables."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if "/" in value:
        ip, _, mask = value.partition("/")
        if not mask.isdigit() or not (0 <= int(mask) <= 32):
            return False
        return is_valid_ipv4(ip)
    return is_valid_ipv4(value)


def is_safe_name(value: str) -> bool:
    """True, если имя состоит только из [a-z0-9-] (не может содержать
    метасимволов shell, слэшей, точек). Для имён ВМ, пулов и т.п."""
    return isinstance(value, str) and bool(_SAFE_NAME_RE.match(value))


def port_is_open(host: str, port: int, timeout: float = 0.4) -> bool:
    """Слушает ли кто-нибудь TCP-порт. Пробник, а не проверка доступности.

    Нужен, чтобы панель не предлагала ссылку, которая заведомо не откроется.
    Конкретный случай: рядом с рабочей HTTP-ссылкой всегда показывалась
    https://хост:44300+ID, хотя TLS не настраивает ни один шаблон окружения —
    на 443 внутри гостя не слушает никто, и половина показанных ссылок была
    мёртвой. Со стороны это выглядит ровно как «доступа нет».

    Таймаут короткий: это соседний адрес в локальной сети, а отказ в
    соединении приходит сразу. False при любой ошибке — пробник не должен
    ронять выдачу сведений о ВМ.
    """
    import socket
    if not is_valid_ipv4(host):
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False
