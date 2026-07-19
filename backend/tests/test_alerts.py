import os
import sys
import types
from datetime import datetime

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import alerts


# ------------------------------ Чистая логика -------------------------------

def test_is_breach_numeric():
    assert alerts.is_breach("cpu_percent", ">", 80, 90) is True
    assert alerts.is_breach("cpu_percent", ">", 80, 50) is False
    assert alerts.is_breach("memory_percent", "<", 10, 5) is True
    assert alerts.is_breach("memory_percent", "<", 10, 50) is False


def test_is_breach_status():
    assert alerts.is_breach("status", ">", None, 0.0) is True   # недоступен
    assert alerts.is_breach("status", ">", None, 1.0) is False  # Running


def test_is_breach_none_value():
    assert alerts.is_breach("cpu_percent", ">", 80, None) is False


def test_parsers():
    assert alerts._parse_k8s_mem("1024Ki") == 1024 * 1024
    assert alerts._parse_k8s_mem("2Mi") == 2 * 1024 * 1024
    assert alerts._parse_cpu_milli("2000m") == 2000
    assert alerts._parse_cpu_milli("1500000000n") == 1500
    assert alerts._parse_cpu_milli("2") == 2000


def test_format_message_status_and_numeric():
    rule = types.SimpleNamespace(name="down", target_name="vm1", metric="status", comparator=">", threshold=None)
    assert "сработал" in alerts.format_message(rule, "firing", 0.0)
    assert "восстановлен" in alerts.format_message(rule, "ok", 1.0)
    rule2 = types.SimpleNamespace(name="cpu", target_name="host", metric="cpu_percent", comparator=">", threshold=80)
    assert "90%" in alerts.format_message(rule2, "firing", 90)


def test_read_host_metrics():
    class Meta: name = "node1"
    class Status: capacity = {"cpu": "4", "memory": "8000000Ki"}
    node = types.SimpleNamespace(metadata=Meta(), status=Status())
    core = types.SimpleNamespace(list_node=lambda: types.SimpleNamespace(items=[node]))
    custom = types.SimpleNamespace(
        get_cluster_custom_object=lambda **k: {"usage": {"cpu": "2000m", "memory": "4000000Ki"}}
    )
    k8s = types.SimpleNamespace(core_api=core, custom_api=custom)
    hm = alerts.read_host_metrics(k8s)
    assert hm["cpu_percent"] == 50.0
    assert hm["memory_percent"] == 50.0


# --------------------- Тик оценки правила (со стейт-мока) --------------------

class FakeQuery:
    def __init__(self, result): self.result = result
    def filter(self, *a, **k): return self
    def first(self): return self.result


class FakeDB:
    def __init__(self, channel): self._channel = channel; self.commits = 0
    def query(self, model): return FakeQuery(self._channel)
    def commit(self): self.commits += 1


def _rule(**kw):
    base = dict(id=1, name="r", target_name="vm1", metric="cpu_percent", comparator=">",
                threshold=80, channel_id=5, state="ok", last_value=None, last_checked=None,
                last_state_change=None, last_notified=None, last_error=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_evaluate_rule_fires_and_notifies(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "read_metric_value", lambda k, db, rule: (95.0, None))
    monkeypatch.setattr(alerts, "send_via_channel", lambda ch, rule, state, val: sent.append((state, val)))
    rule = _rule(state="ok")
    db = FakeDB(types.SimpleNamespace(id=5, enabled=True, type="webhook"))
    alerts._evaluate_rule(None, db, rule, datetime.utcnow())
    assert rule.state == "firing"
    assert sent == [("firing", 95.0)]
    assert rule.last_value == 95.0
    assert rule.last_notified is not None


def test_evaluate_rule_no_notify_when_unchanged(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "read_metric_value", lambda k, db, rule: (95.0, None))
    monkeypatch.setattr(alerts, "send_via_channel", lambda *a: sent.append(a))
    rule = _rule(state="firing")  # уже в firing — уведомления быть не должно
    alerts._evaluate_rule(None, FakeDB(None), rule, datetime.utcnow())
    assert rule.state == "firing"
    assert sent == []


def test_evaluate_rule_recovers(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "read_metric_value", lambda k, db, rule: (10.0, None))
    monkeypatch.setattr(alerts, "send_via_channel", lambda ch, rule, state, val: sent.append(state))
    rule = _rule(state="firing")
    db = FakeDB(types.SimpleNamespace(id=5, enabled=True, type="webhook"))
    alerts._evaluate_rule(None, db, rule, datetime.utcnow())
    assert rule.state == "ok"
    assert sent == ["ok"]


def test_evaluate_rule_missing_data_keeps_state(monkeypatch):
    monkeypatch.setattr(alerts, "read_metric_value", lambda k, db, rule: (None, "нет данных"))
    rule = _rule(state="ok")
    alerts._evaluate_rule(None, FakeDB(None), rule, datetime.utcnow())
    assert rule.state == "ok"
    assert rule.last_error == "нет данных"
