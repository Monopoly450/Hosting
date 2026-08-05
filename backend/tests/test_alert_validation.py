"""Каналы и правила алертов не должны создаваться заведомо нерабочими."""
import pytest
from fastapi import HTTPException

from app.api.alerts import _validate_channel_config, _validate_threshold, _validate_rule_name

GOOD_TOKEN = "123456789:EXAMPLE-NOT-A-REAL-TOKEN-0000000000"


def _err(fn, *args):
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    assert exc.value.status_code == 400
    return exc.value.detail


# ------------------------------- Telegram -----------------------------------

def test_valid_telegram_config_passes():
    _validate_channel_config("telegram", {"bot_token": GOOD_TOKEN, "chat_id": "-1001234567890"})


def test_channel_username_is_accepted_as_chat_id():
    _validate_channel_config("telegram", {"bot_token": GOOD_TOKEN, "chat_id": "@my_alerts"})


@pytest.mark.parametrize("token", [
    "не-токен",
    "EXAMPLE-NOT-A-REAL-TOKEN-0000000000",   # потеряна часть до двоеточия
    "123456789:",                            # скопирован не весь токен
    "123456789:short",
    "123456789 EXAMPLE-NOT-A-REAL-TOKEN-00",  # пробел вместо двоеточия
])
def test_malformed_bot_token_is_rejected(token):
    """Раньше проходила любая непустая строка: канал создавался молча и
    «работал» до первого настоящего алерта, который просто не приходил."""
    detail = _err(_validate_channel_config, "telegram", {"bot_token": token, "chat_id": "1"})
    assert "bot_token" in detail


@pytest.mark.parametrize("chat", ["не число", "chat", "@ab", "12a34"])
def test_malformed_chat_id_is_rejected(chat):
    detail = _err(_validate_channel_config, "telegram", {"bot_token": GOOD_TOKEN, "chat_id": chat})
    assert "chat_id" in detail


def test_missing_telegram_fields_are_rejected():
    _err(_validate_channel_config, "telegram", {})
    _err(_validate_channel_config, "telegram", {"bot_token": GOOD_TOKEN})


def test_whitespace_only_values_are_not_accepted():
    _err(_validate_channel_config, "telegram", {"bot_token": "   ", "chat_id": "   "})


# -------------------------------- Пороги ------------------------------------

@pytest.mark.parametrize("value", [0, 50, 80.5, 100])
def test_sane_percent_thresholds_pass(value):
    _validate_threshold("cpu_percent", value)


def test_threshold_above_100_is_rejected():
    """Правило «CPU > 150%» создавалось молча и не срабатывало никогда."""
    detail = _err(_validate_threshold, "cpu_percent", 150)
    assert "процент" in detail


def test_negative_threshold_is_rejected():
    """А «CPU > -5%» — наоборот, срабатывает всегда и заваливает канал."""
    _err(_validate_threshold, "memory_percent", -5)


def test_non_percent_metric_is_not_range_checked():
    """status процентом не является — ограничение к нему не применяется."""
    _validate_threshold("status", 12345)


# --------------------------------- Имена ------------------------------------

@pytest.mark.parametrize("name", ["", "   ", None])
def test_empty_rule_name_is_rejected(name):
    _err(_validate_rule_name, name)


def test_normal_rule_name_passes():
    _validate_rule_name("CPU выше 90%")
