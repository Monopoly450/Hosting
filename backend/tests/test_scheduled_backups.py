import os
import sys
from datetime import datetime

# Тестовое окружение должно быть настроено до импорта модулей приложения
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.scheduled_backups import compute_next_run, _backup_timestamp

# Суббота, 18 июля 2026, 14:30 UTC (weekday()==5)
NOW = datetime(2026, 7, 18, 14, 30, 0)


def test_hourly_rolls_to_next_hour_when_minute_passed():
    # минута 15 уже прошла в текущем часу -> следующий час
    assert compute_next_run("hourly", 3, 15, None, NOW) == datetime(2026, 7, 18, 15, 15, 0)


def test_hourly_same_hour_when_minute_ahead():
    assert compute_next_run("hourly", 3, 45, None, NOW) == datetime(2026, 7, 18, 14, 45, 0)


def test_daily_next_day_when_time_passed():
    assert compute_next_run("daily", 3, 0, None, NOW) == datetime(2026, 7, 19, 3, 0, 0)


def test_daily_same_day_when_time_ahead():
    assert compute_next_run("daily", 23, 0, None, NOW) == datetime(2026, 7, 18, 23, 0, 0)


def test_weekly_advances_to_target_weekday():
    # понедельник (0) -> ближайший понедельник 20 июля
    assert compute_next_run("weekly", 3, 0, 0, NOW) == datetime(2026, 7, 20, 3, 0, 0)


def test_weekly_today_when_time_ahead():
    # суббота (5), время ещё не наступило -> сегодня
    assert compute_next_run("weekly", 23, 0, 5, NOW) == datetime(2026, 7, 18, 23, 0, 0)


def test_weekly_next_week_when_time_passed_today():
    # суббота (5), 03:00 уже прошло -> следующая суббота
    assert compute_next_run("weekly", 3, 0, 5, NOW) == datetime(2026, 7, 25, 3, 0, 0)


def test_always_strictly_in_future():
    for freq in ("hourly", "daily", "weekly"):
        assert compute_next_run(freq, NOW.hour, NOW.minute, NOW.weekday(), NOW) > NOW


def test_backup_timestamp_parsing():
    assert _backup_timestamp("web-1-backup-1752849000") == 1752849000
    assert _backup_timestamp("garbage") == 0
