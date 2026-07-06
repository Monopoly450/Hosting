"""Единая логика определения «внутренних» IP-адресов ВМ.

Раньше k8s_client и databases фильтровали адреса по-разному, из-за чего
внешний SSH-порт мог вычисляться от служебного/эфемерного адреса и «плавал»
при каждой перезагрузке. Теперь оба места используют эти функции.
"""

# Служебные подсети, которые нельзя показывать как «внешний» адрес ВМ:
#   10.244. / 10.42.  — pod-сети Kubernetes (Calico / flannel в k3s)
#   10.0.2.           — внутренняя masquerade-сеть KubeVirt
#   127.              — loopback
INTERNAL_IP_PREFIXES = ("10.244.", "10.42.", "10.0.2.", "127.")


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
