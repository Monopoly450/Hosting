"""Создание DNS-записей через API провайдера — чтобы домен подключался сам.

Зачем. Раньше подключение домена выглядело так: добавить его в панели, пойти
к регистратору, руками создать TXT-запись подтверждения, потом A-запись,
вернуться и нажать «Проверить». Токен DNS-провайдера при этом уже лежал в
.env — он нужен Caddy для ACME DNS-01. Тем же токеном можно создать обе
записи самим, и от пользователя останется только ввести домен.

Владение доменом при этом не «пропускается»: наличие API-токена зоны и есть
доказательство владения, причём более сильное, чем TXT-запись, которую этим
же токеном и создают. Если токена нет — всё работает как раньше, панель
показывает записи для ручного создания.

Провайдеры. Cloudflare и Timeweb Cloud: оба умеют перечислить зоны аккаунта,
поэтому зону для `app.sub.example.com` не приходится угадывать по списку
публичных суффиксов — берём самое длинное совпадение по концу имени среди
реально доступных зон.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger("app.services.dns_api")

# Запросы идут синхронно, внутри обработчика «добавить домен»: пользователь
# ждёт ответа и должен сразу узнать, создались записи или нет. Отсюда
# небольшой таймаут — нормальный ответ приходит за доли секунды, а лежащий
# API провайдера не должен превращать добавление домена в минутное зависание.
HTTP_TIMEOUT = 10.0

# Сколько страниц списка зон перебирать. Аккаунт с сотнями зон — редкость, но
# без пагинации зона просто не нашлась бы, и автонастройка молча падала бы на
# «домен не найден среди зон».
MAX_PAGES = 10

# TTL создаваемых записей. Маленький намеренно: ACME-проверка идёт сразу
# после создания TXT, и час кеширования у резолверов означал бы час ожидания.
RECORD_TTL = 120


class DnsError(Exception):
    pass


class DnsProvider:
    """Общий интерфейс. Наследники реализуют три метода ниже."""

    name = ""
    label = ""

    def zones(self) -> list:
        raise NotImplementedError

    def upsert(self, fqdn: str, rtype: str, value: str):
        raise NotImplementedError

    # ---- общее ----

    def zone_for(self, fqdn: str) -> Optional[str]:
        """Зона аккаунта, которой принадлежит имя (самое длинное совпадение).

        Без этого пришлось бы гадать: у `app.example.co.uk` регистрируемая
        часть — `example.co.uk`, а у `app.example.com` — `example.com`, и
        отличить их без списка публичных суффиксов нельзя. Список зон
        аккаунта отвечает на вопрос точно.
        """
        name = fqdn.strip(".").lower()
        best = None
        for zone in self.zones():
            z = zone.strip(".").lower()
            if name == z or name.endswith("." + z):
                if best is None or len(z) > len(best):
                    best = z
        return best

    def subdomain_of(self, fqdn: str, zone: str) -> str:
        """Часть имени слева от зоны; "@" для самой зоны."""
        name = fqdn.strip(".").lower()
        zone = zone.strip(".").lower()
        if name == zone:
            return "@"
        return name[: -(len(zone) + 1)]


def _client(headers: dict):
    import httpx
    return httpx.Client(timeout=HTTP_TIMEOUT, headers=headers)


# ------------------------------- Cloudflare ---------------------------------

class CloudflareDns(DnsProvider):
    name = "cloudflare"
    label = "Cloudflare"
    API = "https://api.cloudflare.com/client/v4"

    def __init__(self, token: str):
        self.token = token
        self._zones = None

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, **kw):
        with _client(self._headers()) as c:
            r = c.request(method, f"{self.API}{path}", **kw)
        try:
            data = r.json()
        except Exception:
            raise DnsError(f"Cloudflare ответил не-JSON ({r.status_code})")
        if not data.get("success", False):
            errs = "; ".join(e.get("message", "") for e in data.get("errors") or []) or r.text[:200]
            raise DnsError(f"Cloudflare: {errs}")
        return data.get("result")

    PER_PAGE = 50          # максимум, который отдаёт Cloudflare за один запрос

    def zones(self) -> list:
        if self._zones is None:
            names = []
            for page in range(1, MAX_PAGES + 1):
                res = self._call("GET", "/zones",
                                 params={"per_page": self.PER_PAGE, "page": page}) or []
                names += [z["name"] for z in res]
                if len(res) < self.PER_PAGE:
                    break
            self._zones = names
        return self._zones

    def _zone_id(self, zone: str) -> str:
        res = self._call("GET", "/zones", params={"name": zone})
        if not res:
            raise DnsError(f"зона {zone} не найдена в аккаунте Cloudflare")
        return res[0]["id"]

    def upsert(self, fqdn: str, rtype: str, value: str):
        zone = self.zone_for(fqdn)
        if not zone:
            return False, f"домен {fqdn} не найден среди зон Cloudflare этого токена"
        zid = self._zone_id(zone)
        existing = self._call("GET", f"/zones/{zid}/dns_records",
                              params={"type": rtype, "name": fqdn}) or []
        # proxied=False обязателен: «оранжевое облако» подменяет A-запись
        # адресами Cloudflare, и наша же проверка A-записи после этого не
        # сойдётся. Проксирование включается отдельно и осознанно.
        body = {"type": rtype, "name": fqdn, "content": value,
                "ttl": RECORD_TTL, "proxied": False}
        if existing:
            self._call("PUT", f"/zones/{zid}/dns_records/{existing[0]['id']}", json=body)
            return True, f"запись {rtype} {fqdn} обновлена в Cloudflare"
        self._call("POST", f"/zones/{zid}/dns_records", json=body)
        return True, f"запись {rtype} {fqdn} создана в Cloudflare"


# ------------------------------ Timeweb Cloud --------------------------------

class TimewebDns(DnsProvider):
    name = "timeweb"
    label = "Timeweb Cloud"
    API = "https://api.timeweb.cloud/api/v1"

    def __init__(self, token: str):
        self.token = token
        self._zones = None

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, **kw):
        with _client(self._headers()) as c:
            r = c.request(method, f"{self.API}{path}", **kw)
        if r.status_code >= 400:
            raise DnsError(f"Timeweb ответил {r.status_code}: {r.text[:200]}")
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:
            raise DnsError(f"Timeweb ответил не-JSON ({r.status_code})")

    PER_PAGE = 100

    def zones(self) -> list:
        if self._zones is None:
            names = []
            for page in range(MAX_PAGES):
                data = self._call("GET", "/domains",
                                  params={"limit": self.PER_PAGE,
                                          "offset": page * self.PER_PAGE}) or {}
                chunk = data.get("domains") or []
                names += [d.get("fqdn", "") for d in chunk if d.get("fqdn")]
                if len(chunk) < self.PER_PAGE:
                    break
            self._zones = names
        return self._zones

    def _records(self, zone: str) -> list:
        data = self._call("GET", f"/domains/{zone}/dns-records") or {}
        return data.get("dns_records") or []

    def upsert(self, fqdn: str, rtype: str, value: str):
        zone = self.zone_for(fqdn)
        if not zone:
            return False, f"домен {fqdn} не найден среди доменов Timeweb этого токена"
        sub = self.subdomain_of(fqdn, zone)
        body = {"type": rtype, "value": value}
        if sub != "@":
            body["subdomain"] = sub

        for rec in self._records(zone):
            same_type = (rec.get("type") == rtype)
            rec_sub = rec.get("subdomain") or "@"
            if same_type and rec_sub == sub:
                rid = rec.get("id")
                # У Timeweb нет частичного обновления записи — пересоздаём.
                self._call("DELETE", f"/domains/{zone}/dns-records/{rid}")
                self._call("POST", f"/domains/{zone}/dns-records", json=body)
                return True, f"запись {rtype} {fqdn} обновлена в Timeweb"

        self._call("POST", f"/domains/{zone}/dns-records", json=body)
        return True, f"запись {rtype} {fqdn} создана в Timeweb"


# ------------------------------ Выбор провайдера -----------------------------

def cloudflare_token() -> str:
    return os.getenv("CLOUDFLARE_DNS_API_TOKEN", "")


def timeweb_token() -> str:
    return os.getenv("TIMEWEB_DNS_API_TOKEN", "")


def configured_provider() -> Optional[DnsProvider]:
    """Провайдер из .env или None. Cloudflare приоритетнее, если заданы оба —
    произвольный, но однозначный порядок лучше, чем зависящий от словаря."""
    if cloudflare_token():
        return CloudflareDns(cloudflare_token())
    if timeweb_token():
        return TimewebDns(timeweb_token())
    return None


def automation() -> dict:
    """Что показать интерфейсу: доступна ли автонастройка DNS и чья."""
    p = configured_provider()
    return {
        "dns_automation": bool(p),
        "dns_provider": p.name if p else "",
        "dns_provider_label": p.label if p else "",
    }


def setup_records(fqdn: str, token_value: str, ip: str) -> dict:
    """Создаёт обе записи для домена: TXT подтверждения и A на этот сервер.

    Ничего не бросает: автонастройка — удобство поверх ручного пути, и её
    сбой должен превращаться в понятное сообщение, а не в 500 на добавлении
    домена.
    """
    from app.services.domains import challenge_record_name

    provider = configured_provider()
    if not provider:
        return {"auto": False, "reason": "не задан API-токен DNS-провайдера"}

    steps, errors = [], []
    for rtype, name, value in (
        ("TXT", challenge_record_name(fqdn), token_value),
        ("A", fqdn, ip),
    ):
        try:
            ok, detail = provider.upsert(name, rtype, value)
        except DnsError as e:
            ok, detail = False, str(e)
        except Exception as e:                                  # сеть, таймаут
            logger.warning(f"setup_records {rtype} {name}: {e}")
            ok, detail = False, f"{type(e).__name__}: {e}"
        (steps if ok else errors).append(detail)

    return {
        "auto": not errors,
        "provider": provider.name,
        "steps": steps,
        "errors": errors,
        "reason": "; ".join(errors) if errors else "",
    }
