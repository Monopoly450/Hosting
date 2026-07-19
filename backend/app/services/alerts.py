"""Движок алертов: чтение метрик, вычисление состояния и доставка уведомлений.

Демон в воркере периодически вызывает `evaluate_alerts`. Уведомление шлётся
только при СМЕНЕ состояния правила (ok<->firing), чтобы не спамить.
Каналы доставки: webhook (JSON POST) и Telegram (sendMessage).
"""
import json
import logging
import urllib.request
from datetime import datetime

logger = logging.getLogger("app.services.alerts")

# Доступные метрики по типу цели
METRIC_CATALOG = {
    "vm": ["status", "cpu_percent", "memory_percent"],
    "host": ["cpu_percent", "memory_percent"],
}
NUMERIC_METRICS = {"cpu_percent", "memory_percent"}


# ------------------------------ Чистая логика -------------------------------

def is_breach(metric: str, comparator: str, threshold, value) -> bool:
    """Нарушено ли условие правила при текущем значении метрики (чистая функция)."""
    if value is None:
        return False
    if metric == "status":
        return value < 1.0  # 1.0 = здоров (Running), 0.0 = недоступен
    if threshold is None:
        return False
    if comparator == "<":
        return value < threshold
    return value > threshold


# ------------------------------ Парсеры k8s ---------------------------------

def _parse_k8s_mem(mem_str) -> int:
    if not mem_str:
        return 0
    if mem_str.endswith("Ki"):
        return int(mem_str[:-2]) * 1024
    if mem_str.endswith("Mi"):
        return int(mem_str[:-2]) * 1024 * 1024
    if mem_str.endswith("Gi"):
        return int(mem_str[:-2]) * 1024 * 1024 * 1024
    try:
        return int(mem_str)
    except ValueError:
        return 0


def _parse_cpu_milli(cpu_str) -> float:
    if not cpu_str:
        return 0.0
    if cpu_str.endswith("n"):
        return int(cpu_str[:-1]) / 1000000
    if cpu_str.endswith("u"):
        return int(cpu_str[:-1]) / 1000
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    return float(cpu_str) * 1000


def read_host_metrics(k8s):
    """CPU/RAM хоста в процентах из metrics.k8s.io. None, если недоступно."""
    try:
        nodes = k8s.core_api.list_node()
        if not nodes.items:
            return None
        node = nodes.items[0]
        cap = node.status.capacity
        cpu_cap = int(cap.get("cpu", 1))
        mem_cap = _parse_k8s_mem(cap.get("memory"))

        nm = k8s.custom_api.get_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes", name=node.metadata.name
        )
        cpu_milli = _parse_cpu_milli(nm.get("usage", {}).get("cpu", "0n"))
        mem_bytes = _parse_k8s_mem(nm.get("usage", {}).get("memory", "0Ki"))
        return {
            "cpu_percent": round(cpu_milli / (cpu_cap * 1000) * 100, 1) if cpu_cap else 0.0,
            "memory_percent": round(mem_bytes / mem_cap * 100, 1) if mem_cap else 0.0,
        }
    except Exception as e:
        logger.warning(f"read_host_metrics: {e}")
        return None


def read_metric_value(k8s, db, rule):
    """Возвращает (value, error). value — число; для status 1.0=здоров, 0.0=нет.
    None value означает «данные недоступны» — состояние правила не трогаем."""
    from app.models.models import VMTask

    if rule.target_type == "host":
        hm = read_host_metrics(k8s)
        if hm is None:
            return None, "метрики хоста недоступны"
        return hm.get(rule.metric), None

    if rule.target_type == "vm":
        vm = db.query(VMTask).filter(VMTask.id == rule.target_id).first()
        if not vm:
            return None, "ВМ не найдена"
        if rule.metric == "status":
            try:
                info = k8s.get_vm(vm.name)
            except Exception as e:
                return None, f"нет данных о ВМ: {e}"
            return (1.0 if info.get("status") == "Running" else 0.0), None

        # cpu_percent / memory_percent
        try:
            m = k8s.get_vm_metrics(vm.name)
        except Exception as e:
            return None, f"нет метрик ВМ: {e}"
        if m.get("status") != "Running":
            return 0.0, None  # выключенная ВМ не потребляет ресурсы
        if rule.metric == "cpu_percent":
            cpu_milli = m.get("cpu_milli")
            if cpu_milli is None:
                return None, "нет метрик CPU"
            cores = vm.cpu_cores or 1
            return round(cpu_milli / (cores * 1000) * 100, 1), None
        if rule.metric == "memory_percent":
            mb = m.get("memory_mb")
            if mb is None:
                return None, "нет метрик RAM"
            gb = vm.memory_gb or 1
            return round(mb / (gb * 1024) * 100, 1), None

    return None, "неизвестная метрика"


# ---------------------------- Доставка уведомлений --------------------------

def format_message(rule, state: str, value) -> str:
    if state == "firing":
        head = f"🔴 Алерт сработал: {rule.name}"
    else:
        head = f"✅ Алерт восстановлен: {rule.name}"
    if rule.metric == "status":
        cond = "недоступен (не Running)" if state == "firing" else "снова доступен"
        return f"{head}\nОбъект: {rule.target_name}\nСостояние: {cond}"
    return (f"{head}\nОбъект: {rule.target_name}\n"
            f"{rule.metric} = {value}% (порог {rule.comparator} {rule.threshold}%)")


def _http_post_json(url: str, payload: dict, timeout: int = 10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def send_via_channel(channel, rule, state: str, value):
    """Отправляет уведомление в канал. Секреты берём из зашифрованного config."""
    from app.core.crypto import decrypt_secret
    cfg = json.loads(decrypt_secret(channel.config))
    text = format_message(rule, state, value)

    if channel.type == "telegram":
        token = cfg.get("bot_token")
        chat_id = cfg.get("chat_id")
        if not token or not chat_id:
            raise ValueError("Не заданы bot_token/chat_id")
        _http_post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": chat_id, "text": text})
    elif channel.type == "webhook":
        url = cfg.get("url")
        if not url:
            raise ValueError("Не задан url")
        _http_post_json(url, {
            "alert": rule.name, "state": state, "target": rule.target_name,
            "metric": rule.metric, "value": value, "threshold": rule.threshold, "text": text,
        })
    else:
        raise ValueError(f"Неизвестный тип канала: {channel.type}")


# ------------------------------ Тик демона ----------------------------------

def _evaluate_rule(k8s, db, rule, now):
    from app.models.models import NotificationChannel

    value, err = read_metric_value(k8s, db, rule)
    rule.last_checked = now
    if value is None:
        rule.last_error = err
        db.commit()
        return
    rule.last_error = None
    rule.last_value = value

    new_state = "firing" if is_breach(rule.metric, rule.comparator, rule.threshold, value) else "ok"
    if new_state != rule.state:
        rule.state = new_state
        rule.last_state_change = now
        if rule.channel_id:
            channel = db.query(NotificationChannel).filter(NotificationChannel.id == rule.channel_id).first()
            if channel and channel.enabled:
                try:
                    send_via_channel(channel, rule, new_state, value)
                    rule.last_notified = now
                except Exception as e:
                    logger.error(f"Алерт #{rule.id}: не удалось отправить уведомление: {e}")
                    rule.last_error = f"уведомление не доставлено: {e}"
    db.commit()


def evaluate_alerts(k8s):
    """Один тик: проверяет все включённые правила и шлёт уведомления при смене состояния."""
    from app.db import SessionLocal
    from app.models.models import AlertRule

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        rules = db.query(AlertRule).filter(AlertRule.enabled == True).all()  # noqa: E712
        for rule in rules:
            try:
                _evaluate_rule(k8s, db, rule, now)
            except Exception as e:
                logger.error(f"Ошибка проверки правила #{rule.id}: {e}")
                db.rollback()
    finally:
        db.close()
