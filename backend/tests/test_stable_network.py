"""Регрессионные тесты для сети ВМ на мосту br-vms.

Раньше маркетплейс и деплой из GitHub писали в cloud-init собственный
netplan с dhcp4 на ВСЕ "e*"-интерфейсы вместо статического адреса на
мостовом интерфейсе — второй (br-vms) интерфейс получал случайную аренду
DHCP вместо детерминированного 172.20.0.<30+id%200>, из-за чего адрес
«плавал» между перезагрузками, а в редких случаях мог совпасть с чужой
статической ВМ. Плюс — установка qemu-guest-agent (единственный канал, по
которому KubeVirt узнаёт IP мостового интерфейса) была одной попыткой без
повтора, в отличие от обычных ВМ.
"""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from app.services.cloudinit import build_network_data, GUEST_AGENT_RETRY_RUNCMD
from app.services import marketplace as mp

POD_MAC = "02:00:00:11:22:33"
LAN_MAC = "02:00:00:44:55:66"


def test_static_ip_pins_bridge_interface_by_mac():
    nd = yaml.safe_load(build_network_data(POD_MAC, LAN_MAC, "172.20.0.130"))
    assert nd["version"] == 2
    stable = nd["ethernets"]["stable-nic"]
    assert stable["match"]["macaddress"] == LAN_MAC
    assert stable["dhcp4"] is False
    assert stable["addresses"] == ["172.20.0.130/24"]
    # pod-интерфейс всегда DHCP — интернет/сеть кластера
    pod = nd["ethernets"]["pod-nic"]
    assert pod["match"]["macaddress"] == POD_MAC
    assert pod["dhcp4"] is True


def test_without_static_ip_bridge_falls_back_to_dhcp():
    nd = yaml.safe_load(build_network_data(POD_MAC, LAN_MAC, None))
    assert nd["ethernets"]["stable-nic"]["dhcp4"] is True
    assert "addresses" not in nd["ethernets"]["stable-nic"]


def test_guest_agent_install_covers_every_package_manager():
    # Регрессия 1: раньше была ОДНА попытка apt-get без повтора — единственная
    # транзиентная неудача (занятый dpkg-лок сразу после загрузки) навсегда
    # лишала ВМ видимого мостового IP, т.к. агент никто не переустанавливал.
    assert "while" in GUEST_AGENT_RETRY_RUNCMD
    assert "sleep 5" in GUEST_AGENT_RETRY_RUNCMD
    # Регрессия 2: перебирались только apt/dnf/yum, поэтому на openSUSE, Arch
    # и Alpine агент не ставился вообще и адрес мостового интерфейса не
    # становился известен панели никогда.
    for pm in ("apt-get", "dnf", "yum", "zypper", "pacman", "apk"):
        assert pm in GUEST_AGENT_RETRY_RUNCMD, pm
    # В Alpine нет systemd — нужен запасной путь через OpenRC
    assert "rc-update add qemu-guest-agent" in GUEST_AGENT_RETRY_RUNCMD


def test_marketplace_cloud_init_no_longer_configures_network():
    """Сеть задаётся networkData в манифесте, а не файлом netplan в cloud-init.

    netplan есть только в Ubuntu; когда каждый сборщик писал свой файл, их
    приходилось держать синхронными вручную, и любое расхождение возвращало
    «плавающий» адрес на мосту."""
    app = mp.get_app("nextcloud")
    env = mp.add_public_url(mp.resolve_env(app, {}), "192.168.31.10", 28014)
    ci = mp.build_marketplace_cloud_init(app, env, "pw")
    doc = yaml.safe_load(ci)
    files = {f["path"]: f["content"] for f in doc["write_files"]}
    assert "/etc/netplan/99-dhcp.yaml" not in files
    assert "netplan apply" not in ci
    # Compose и .env по-прежнему на месте
    assert "/opt/app/docker-compose.yml" in files
    assert "/opt/app/.env" in files


def test_ip_rule_matching_does_not_hit_other_vms_by_substring():
    """Реальный баг: голое `vm_ip in line` считало 172.20.0.13 совпавшим с
    правилом для 172.20.0.130 (один просто префикс другого). При каждой смене
    IP какой-нибудь ВМ это могло стереть DNAT/FORWARD правило совсем другой
    машины, у которой адрес не менялся — сайты переставали открываться, а SSH
    отваливался без видимой причины."""
    from app.api.vms import _ip_in_rule

    assert not _ip_in_rule(
        "172.20.0.13",
        "-A PREROUTING -p tcp --dport 28014 -j DNAT --to-destination 172.20.0.130:80",
    )
    assert _ip_in_rule(
        "172.20.0.13",
        "-A PREROUTING -p tcp --dport 22013 -j DNAT --to-destination 172.20.0.13:22",
    )
    assert _ip_in_rule("172.20.0.13", "-A FORWARD -p tcp -d 172.20.0.13/32 --dport 80 -j ACCEPT")
    assert not _ip_in_rule("20.0.13", "-A FORWARD -p tcp -d 172.20.0.130 --dport 80 -j ACCEPT")


def test_resolve_vm_ip_matches_pick_external_ip():
    """vms.resolve_vm_ip раньше был отдельной копией той же фильтрации и не
    знал про 192.168.100.x (сеть изоляции кластеров) — SSH/терминал ВМ в
    кластере мог получить как «внешний» адрес изоляции вместо настоящего
    маршрутизируемого с хоста IP. Теперь это алиас pick_external_ip."""
    from app.api.vms import resolve_vm_ip
    from app.core.netutils import pick_external_ip

    cases = [
        ["10.244.0.1", "192.168.100.5", "172.20.0.99"],
        ["192.168.100.5", "10.42.0.9"],
        ["192.168.100.5"],
        [],
    ]
    for ips in cases:
        assert resolve_vm_ip(ips) == pick_external_ip(ips)
    assert resolve_vm_ip(["192.168.100.5", "10.42.0.9"]) == "10.42.0.9"


# ---------- мосты Docker внутри гостя не должны выдаваться за адрес ВМ -------
#
# Живой инцидент: у ВМ с Grafana панель показывала IP 172.17.0.1 и туда же
# уходил DNAT проброса портов. Это docker0 ВНУТРИ гостя — он появляется, как
# только шаблон (docker/portainer/grafana) или приложение маркетплейса ставит
# Docker. На хосте 172.17.0.1 — его собственный docker0, поэтому проброс уводил
# трафик в никуда: сайт не открывался, SSH по проброшенному порту рвался.

def test_docker0_inside_the_guest_is_not_taken_for_the_vm_address():
    from app.core.netutils import pick_external_ip, is_internal_ip

    assert is_internal_ip("172.17.0.1") is True
    # реальный набор с ВМ, где поставили Docker
    assert pick_external_ip(["172.17.0.1", "172.20.0.42"]) == "172.20.0.42"


def test_docker_user_defined_networks_are_also_ignored():
    """Compose-стеки создают свои сети: 172.18.0.1, 172.19.0.1 и далее."""
    from app.core.netutils import is_internal_ip

    for octet in (17, 18, 19, 21, 22, 31):
        assert is_internal_ip(f"172.{octet}.0.1") is True, octet


def test_br_vms_subnet_is_not_swallowed_by_the_docker_range():
    """172.20.0.0/24 — наш собственный мост br-vms (см. install.sh), настоящий
    адрес обычных ВМ. Он лежит внутри диапазона, который Docker занимает по
    умолчанию, поэтому исключать 172.16/12 целиком нельзя."""
    from app.core.netutils import is_internal_ip, pick_external_ip

    assert is_internal_ip("172.20.0.55") is False
    assert pick_external_ip(["10.42.0.9", "172.20.0.55"]) == "172.20.0.55"


def test_vm_with_docker_still_reports_its_bridge_address_not_docker0():
    """Порядок в списке от qemu-guest-agent не гарантирован — docker0 может
    прийти первым."""
    from app.core.netutils import pick_external_ip

    assert pick_external_ip(["172.17.0.1", "10.42.0.9", "172.20.0.7"]) == "172.20.0.7"
    assert pick_external_ip(["172.20.0.7", "172.17.0.1"]) == "172.20.0.7"


def test_cluster_isolated_network_is_still_excluded():
    """Решение коммита 135746d: подсеть 192.168.100.0/24 одинакова у ВСЕХ
    кластеров, поэтому с хоста она неоднозначна и проброс идёт на Pod IP.
    Правка про docker0 это поведение менять не должна."""
    from app.core.netutils import is_internal_ip, pick_external_ip

    assert is_internal_ip("192.168.100.5") is True
    assert pick_external_ip(["192.168.100.5", "10.42.0.9"]) == "10.42.0.9"


# --------------- порты по умолчанию: одна арифметика на всех ----------------

def test_default_ports_are_stable_and_derived_from_the_vm_id():
    from app.api.vms import default_ports_for

    ports = {p["int_port"]: p["ext_port"] for p in default_ports_for(71)}
    assert ports == {22: 22071, 80: 28071, 443: 44371}


def test_windows_gets_rdp_instead_of_https():
    from app.api.vms import default_ports_for

    names = {p["name"] for p in default_ports_for(71, "windows")}
    assert "RDP" in names and "HTTPS" not in names


def test_resolve_vm_ports_fallback_matches_default_ports_for():
    """Ключевой инвариант: список, который панель показывает, и список, по
    которому вотчдог ставит правила в iptables, обязаны совпадать. Раньше эта
    арифметика была скопирована в трёх местах и могла разъехаться."""
    from app.api.vms import default_ports_for, resolve_vm_ports

    for os_type in ("linux", "windows"):
        assert resolve_vm_ports("172.20.0.71", 71, None, os_type) == \
            default_ports_for(71, os_type)


def test_templates_with_their_own_port_get_a_forwarding_rule():
    """Живой симптом «некоторые шаблоны не работают»: Portainer слушает 9000,
    Grafana — 3000, а порты по умолчанию только 22/80/443. Сервис внутри ВМ
    поднимался, но снаружи его было не достать вообще."""
    from app.api.vms import default_ports_for

    graf = {p["int_port"] for p in default_ports_for(71, "linux", "grafana")}
    port = {p["int_port"] for p in default_ports_for(71, "linux", "portainer")}
    assert 3000 in graf
    assert 9000 in port


def test_web_templates_do_not_get_a_duplicate_port():
    """LAMP, LEMP, WordPress и Zabbix слушают 80 — он уже проброшен, второй
    записи быть не должно."""
    from app.api.vms import default_ports_for

    for tpl in ("lamp", "lemp", "wordpress", "zabbix"):
        ports = [p["int_port"] for p in default_ports_for(71, "linux", tpl)]
        assert ports == [22, 80, 443], tpl
        assert len(ports) == len(set(ports)), tpl


def test_database_templates_are_not_exposed_by_default():
    """PostgreSQL и Redis по умолчанию слушают только localhost — проброс вёл
    бы в никуда, а порт БД наружу открывать без нужды не стоит."""
    from app.api.vms import default_ports_for

    for tpl in ("postgresql", "redis"):
        ports = [p["int_port"] for p in default_ports_for(71, "linux", tpl)]
        assert 5432 not in ports and 6379 not in ports, tpl


def test_external_ports_of_a_template_do_not_collide_with_the_standard_ones():
    from app.api.vms import default_ports_for

    ext = [p["ext_port"] for p in default_ports_for(71, "linux", "grafana")]
    assert len(ext) == len(set(ext))


# ----- порт собственного сервиса шаблона должен доезжать до интерфейса ------
#
# Живой случай: Grafana в кластере поднялась, контейнер Up, проброс 29009→3000
# создан — а карточка ВМ показывала только ссылки на 28009 (порт 80) и 44309
# (443), где у Grafana не слушает никто. Обе честно писали «пока не отвечает»,
# а единственный рабочий адрес не показывался нигде: выглядело как «шаблон не
# работает», хотя работало всё, кроме подсказки.

def test_app_port_entry_is_named_so_the_api_can_find_it():
    """Карточка ВМ ищет проброс приложения по имени APP — переименование
    молча лишило бы её рабочей ссылки."""
    from app.api.vms import default_ports_for
    app = [p for p in default_ports_for(9, "ubuntu", "grafana") if p["name"] == "APP"]
    assert app == [{"ext_port": 29009, "int_port": 3000, "name": "APP"}]


def test_vm_payload_exposes_the_app_port():
    """get_vm обязан отдавать app_port/app_int_port — иначе интерфейсу нечего
    показать, даже когда проброс существует."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "core", "k8s_client.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert '"app_port": app_port' in src
    assert '"app_int_port": app_int_port' in src
    assert 'p.get("name") == "APP"' in src


def test_ui_shows_the_app_link():
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend", "src", "components", "VMDetail.jsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "vm.app_port" in src, "карточка ВМ не показывает адрес приложения"


def test_templates_without_their_own_port_have_no_app_entry():
    """У lamp/wordpress сервис и так на 80 — лишний проброс только запутает."""
    from app.api.vms import default_ports_for
    for tpl in ("lamp", "lemp", "wordpress", "zabbix", "docker", "nodejs"):
        names = {p["name"] for p in default_ports_for(9, "ubuntu", tpl)}
        assert "APP" not in names, tpl
