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
    for ip in ips:
        if not is_internal_ip(ip):
            return ip
    for ip in ips:
        if ":" not in ip:
            return ip
    return ips[0]
