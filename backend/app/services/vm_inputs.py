"""Validation and deterministic composition of the VM creation fields.

Only #cloud-config YAML can be merged. Custom commands are trusted guest code,
not executed on the hosting server. Schema validation is entirely offline.
"""
import copy
import ipaddress
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from jsonschema import Draft4Validator


def dns_name(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", value):
        raise ValueError("Имя: 1–63 символа, латинские буквы, цифры и дефис; начало и конец — буква или цифра.")
    return value


def package_name(value: str) -> str:
    # Names, not shell expressions, URLs, switches or translated display names.
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9+_.-]*(?::[a-zA-Z0-9_-]+)?", value):
        raise ValueError("Пакеты: укажите системные имена латиницей через запятую, например htop, curl, jq; команды и пробелы недопустимы.")
    return value


def comma_items(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",")]
    if any(not item for item in items) or len(items) > 32:
        raise ValueError("Укажите не более 32 значений через запятую, без пустых элементов.")
    return list(dict.fromkeys(items))


def packages(value: str) -> str:
    return ", ".join(package_name(item) for item in comma_items(value))


def network_drives(value: str) -> str:
    items = comma_items(value)
    for item in items:
        if ":/" not in item:
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", item):
                raise ValueError("NFS: после IP-адреса укажите путь, например 192.168.1.10:/shared.")
            if len(item) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", item) or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in item.split(".")
            ):
                raise ValueError("Сетевые диски: укажите точное имя PVC латиницей или NFS-адрес вида 192.168.1.10:/shared.")
        else:
            host, path = item.split(":/", 1)
            try:
                ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                if re.fullmatch(r"[0-9.]+", host) or not re.fullmatch(
                    r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host
                ) or any(not label or label.startswith("-") or label.endswith("-") for label in host.split(".")):
                    raise ValueError("NFS: неверный IP-адрес или имя сервера.") from None
            if any(not (char.isalnum() or char in "/._-+@") for char in path):
                raise ValueError("NFS: путь должен быть абсолютным, без пробелов, кавычек и управляющих символов.")
    return ", ".join(items)


def ssh_key(value: str) -> str:
    value = value.strip()
    if "\n" in value or "\r" in value or len(value) > 16384:
        raise ValueError("SSH-ключ: вставьте один публичный ключ одной строкой, не приватный ключ.")
    try:
        load_ssh_public_key(value.encode("utf-8"))
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm):
        raise ValueError("SSH-ключ: неверный публичный ключ. Ожидается ssh-ed25519, ssh-rsa или ecdsa-sha2-… с корректным содержимым.") from None
    return value


def image_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username and not parsed.password
        parsed.port
    except ValueError:
        valid = False
    if not valid or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("Образ: укажите корректную HTTP/HTTPS-ссылку без пробелов и пароля в адресе.")
    return value


class _UniqueLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("Cloud-Init: YAML-ссылки и якоря не поддерживаются.")
        self.depth = getattr(self, "depth", 0) + 1
        if self.depth > 32:
            raise ValueError("Cloud-Init: слишком глубокая вложенность YAML.")
        try:
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in keys:
                raise ValueError("Cloud-Init: ключи YAML должны быть строками и не должны повторяться.")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


@lru_cache(maxsize=1)
def _schema_validator():
    schema = json.loads((Path(__file__).parent / "schemas/cloud-config-26.1.json").read_text())
    return Draft4Validator(schema)


def cloud_config(value: str) -> dict:
    if len(value.encode("utf-8")) > 262144:
        raise ValueError("Cloud-Init: максимальный размер — 256 КиБ.")
    if not value.strip() or value.lstrip().splitlines()[0].strip() != "#cloud-config":
        raise ValueError("Cloud-Init: требуется YAML, начинающийся с #cloud-config; shell-скрипты и MIME в этом поле не поддерживаются.")
    try:
        doc = yaml.load(value, Loader=_UniqueLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" (строка {mark.line + 1}, столбец {mark.column + 1})" if mark else ""
        raise ValueError(f"Cloud-Init: некорректный YAML{location}. Проверьте отступы и кавычки.") from None
    if not isinstance(doc, dict) or not doc:
        raise ValueError("Cloud-Init: после #cloud-config требуется непустой словарь настроек.")
    if "users" in doc and isinstance(doc["users"], (str, dict)):
        doc["users"] = [doc["users"]]
    for flag in ("ssh_pwauth", "disable_root", "package_update", "package_upgrade", "package_reboot_if_required"):
        if flag in doc and not isinstance(doc[flag], bool):
            raise ValueError(f"Cloud-Init: {flag} должен быть true или false, не строкой.")
    errors = list(_schema_validator().iter_errors(doc))
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.absolute_path)) or "корень документа"
        # Never echo a password, private key, file content or command in errors.
        raise ValueError(f"Cloud-Init: неверная структура или неизвестное поле ({location}). Проверьте названия ключей латиницей и типы значений.")
    for key in ("cloud_init_modules", "cloud_config_modules", "cloud_final_modules", "merge_how", "merge_type"):
        if key in doc:
            raise ValueError(f"Cloud-Init: {key} нельзя переопределять при объединении с настройками панели.")
    for key in doc.get("ssh_authorized_keys", []):
        ssh_key(key)
    for user in doc.get("users", []):
        name = user.get("name") if isinstance(user, dict) else user
        if not isinstance(name, str) or not re.fullmatch(r"[a-z_][a-z0-9_.-]{0,31}\$?", name):
            raise ValueError("Cloud-Init: users — список пользователей с именами латиницей; для стандартного пользователя укажите default.")
        if isinstance(user, dict):
            for key in user.get("ssh_authorized_keys", []):
                ssh_key(key)
    for item in doc.get("packages", []):
        package_name(item if isinstance(item, str) else item[0])
    if "timezone" in doc:
        try:
            ZoneInfo(doc["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Cloud-Init: timezone должен быть именем часового пояса, например Asia/Yekaterinburg или UTC.") from None
    for item in doc.get("write_files", []):
        path = item["path"]
        if not path.startswith("/") or any(ord(char) < 32 for char in path):
            raise ValueError("Cloud-Init: write_files.path должен быть абсолютным путём без управляющих символов.")
    return doc


def _merge(base, custom):
    if isinstance(base, dict) and isinstance(custom, dict):
        result = copy.deepcopy(base)
        for key, value in custom.items():
            result[key] = _merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    if isinstance(base, list) and isinstance(custom, list):
        result = copy.deepcopy(base)
        for item in custom:
            # Combine existing users and files by identity, rather than creating
            # two inconsistent user records or writing a file twice.
            identity = next((key for key in ("name", "path") if isinstance(item, dict) and key in item), None)
            match = next((i for i, old in enumerate(result) if identity and isinstance(old, dict) and old.get(identity) == item[identity]), None)
            if match is not None:
                result[match] = _merge(result[match], item)
            elif item not in result:
                result.append(copy.deepcopy(item))
        return result
    return copy.deepcopy(custom)


def merge_cloud_config(generated: str, custom: str, key: str = None) -> str:
    if not custom:
        return generated
    base = yaml.safe_load(generated)
    doc = cloud_config(custom)
    result = _merge(base, doc)
    # Commands are ordered, not sets: deliberately repeated commands must run
    # repeatedly. Panel setup precedes user commands.
    result["runcmd"] = base.get("runcmd", []) + doc.get("runcmd", [])
    if "bootcmd" in base or "bootcmd" in doc:
        result["bootcmd"] = base.get("bootcmd", []) + doc.get("bootcmd", [])
    if key:
        if doc.get("ssh_pwauth") is True:
            raise ValueError("SSH-ключ несовместим с ssh_pwauth: true: вход по паролю должен быть выключен.")
        result["ssh_pwauth"] = False
    # A user-defined password must not be silently replaced by late runcmd.
    if "chpasswd" in doc or "password" in doc or any(
        isinstance(user, dict) and any(field in user for field in ("passwd", "hashed_passwd", "plain_text_passwd"))
        for user in doc.get("users", [])
    ):
        result["runcmd"] = [cmd for cmd in base.get("runcmd", []) if not (
            isinstance(cmd, str) and cmd.startswith("echo ") and " | chpasswd" in cmd
        )] + doc.get("runcmd", [])
    rendered = "#cloud-config\n" + yaml.safe_dump(result, allow_unicode=True, sort_keys=False)
    cloud_config(rendered)
    return rendered
