"""Проверки docker-compose.yml, которые легко сломать незаметно.

Живой инцидент: `${CLOUDFLARE_TUNNEL_TOKEN:?...}` (обязательная переменная)
на сервисе `cloudflared` ломала КАЖДЫЙ `docker compose` (up, ps, даже
--help) на КАЖДОЙ установке — не только у тех, кто подключает Cloudflare
Tunnel. Причина: Docker Compose интерполирует переменные всех сервисов при
разборе файла и только потом фильтрует их по активным профилям — `profiles:`
не защищает `:?required` от срабатывания раньше времени.
"""
import os
import re

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compose_text() -> str:
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        return f.read()


def _compose() -> dict:
    return yaml.safe_load(_compose_text())


def test_compose_file_is_valid_yaml():
    d = _compose()
    assert "cloudflared" in d["services"]


def test_no_required_variable_on_a_profiled_service():
    """Общий случай, а не только cloudflared: `:?` на переменной сервиса,
    у которого есть `profiles:`, ломает compose для всех, кто этот профиль
    не использует — с этим уже наступили один раз."""
    d = _compose()
    for name, svc in d["services"].items():
        if "profiles" not in svc:
            continue
        blob = yaml.dump(svc)
        assert ":?" not in blob, (
            f"сервис {name} под профилем использует обязательную переменную "
            f"(:?) — это ломает docker compose даже без активного профиля"
        )


def test_cloudflare_tunnel_token_has_a_safe_default():
    compose = _compose_text()
    m = re.search(r"cloudflared:.*?(?=\n  \w+:|\Z)", compose, re.S)
    assert m, "сервис cloudflared не найден в docker-compose.yml"
    block = m.group(0)
    assert "CLOUDFLARE_TUNNEL_TOKEN:-" in block
    assert "CLOUDFLARE_TUNNEL_TOKEN:?" not in block


def test_cloudflared_only_starts_under_its_own_profile():
    d = _compose()
    assert d["services"]["cloudflared"]["profiles"] == ["cloudflare"]


def test_mandatory_secrets_still_fail_fast():
    """Обратная сторона того же теста: пароли, нужные ВСЕГДА (не под
    профилем), обязаны остаться обязательными — иначе бэкенд молча
    стартует с пустым паролем к БД."""
    compose = _compose_text()
    for var in ("POSTGRES_PASSWORD", "ADMIN_TOKEN", "RABBITMQ_USER"):
        assert f"{{{var}:?" in compose, f"{var} должен быть обязательным"
