"""Защита от SSRF для исходящих запросов, адрес которых задаёт пользователь.

Бэкенд работает в сети хоста и имеет доступ к служебным адресам: метаданным
облака (169.254.169.254), собственному API панели на localhost, RabbitMQ,
Kubernetes API. Поэтому webhook-адрес, введённый пользователем, нельзя вызывать
без проверки — иначе панель превращается в прокси во внутреннюю сеть.

Проверяем не только строку URL, но и то, во что резолвится имя: иначе
`evil.com`, указывающий A-записью на 127.0.0.1, обойдёт любую проверку по тексту.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")


def allow_private_targets() -> bool:
    """Аварийный выключатель для инсталляций, где webhook во внутреннюю сеть —
    осознанное решение администратора."""
    return os.getenv("ALLOW_PRIVATE_WEBHOOKS", "").lower() in ("1", "true", "yes")


def _ip_is_forbidden(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_loopback          # 127.0.0.0/8, ::1 — само API панели
        or ip.is_private        # 10/8, 172.16/12, 192.168/16 — внутренняя сеть, ВМ
        or ip.is_link_local     # 169.254/16 — метаданные облака
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_targets(hostname: str) -> list:
    """Все адреса, в которые резолвится имя (проверяем каждый)."""
    infos = socket.getaddrinfo(hostname, None)
    out = []
    for family, _, _, _, sockaddr in infos:
        if family in (socket.AF_INET, socket.AF_INET6):
            out.append(ipaddress.ip_address(sockaddr[0]))
    return out


def validate_public_url(url: str) -> str:
    """Проверяет, что URL ведёт на публичный адрес. Бросает ValueError.

    Возвращает исходный URL, чтобы удобно было писать `url = validate_public_url(url)`.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL не задан")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError("Разрешены только адреса http:// и https://")
    if not parsed.hostname:
        raise ValueError("В URL отсутствует имя хоста")

    if allow_private_targets():
        return url

    # Если в URL сразу указан IP — проверяем его напрямую.
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if _ip_is_forbidden(ip):
            raise ValueError(f"Адрес {ip} относится к внутренней сети и запрещён")
        return url
    except ValueError as e:
        if "внутренней сети" in str(e):
            raise

    try:
        targets = resolve_targets(parsed.hostname)
    except Exception as e:
        raise ValueError(f"Имя {parsed.hostname} не резолвится: {e}")

    if not targets:
        raise ValueError(f"Не удалось определить адрес {parsed.hostname}")

    for ip in targets:
        if _ip_is_forbidden(ip):
            raise ValueError(
                f"Имя {parsed.hostname} указывает на внутренний адрес {ip} — запрещено"
            )
    return url
