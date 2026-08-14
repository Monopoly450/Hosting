"""Фильтр списка серверов: данные для него готовит бэкенд.

Искать по имени можно и по тому, что уже лежит в ответе, но «откуда
развёрнута» и «по каким доменам доступна» из голого списка ВМ не вывести:
источник живёт в AppDeployment, домены — в отдельной таблице и могут быть
привязаны как к самой ВМ, так и к её деплою.
"""
import os
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.vms import _enrich_for_filters


def _row(id, name, template=None, cluster_id=None):
    return types.SimpleNamespace(id=id, name=name, cloud_init_template=template,
                                 cluster_id=cluster_id)


def _dep(id, vm_id, stack, repo_url):
    return types.SimpleNamespace(id=id, vm_id=vm_id, stack=stack, repo_url=repo_url)


def _dom(target_type, target_id, domain):
    return types.SimpleNamespace(target_type=target_type, target_id=target_id, domain=domain)


class FakeDb:
    """Отдаёт заранее заданные наборы по типу запрошенной модели."""

    def __init__(self, rows=(), deps=(), clusters=(), domains=()):
        from app.models.models import AppDeployment, Cluster, Domain, VMTask
        self._by_model = {
            VMTask: list(rows), AppDeployment: list(deps),
            Cluster: list(clusters), Domain: list(domains),
        }
        self.queries = 0

    def query(self, model):
        self.queries += 1
        items = self._by_model[model]

        class Q:
            def filter(self, *a, **k):
                return self

            def all(self):
                return items
        return Q()


def _enrich(vms, **kw):
    return _enrich_for_filters(FakeDb(**kw), vms)


# ------------------------------ откуда развёрнута ----------------------------

def test_marketplace_app_is_labelled_by_its_app_id():
    vms = _enrich([{"name": "n8n-1"}],
                  rows=[_row(1, "n8n-1")],
                  deps=[_dep(7, 1, "marketplace", "marketplace://n8n")])
    assert vms[0]["source"] == "Маркетплейс"
    assert vms[0]["source_detail"] == "n8n"


def test_github_deploy_keeps_the_repo_url():
    vms = _enrich([{"name": "blog"}],
                  rows=[_row(1, "blog")],
                  deps=[_dep(7, 1, "compose", "https://github.com/me/blog")])
    assert vms[0]["source"] == "GitHub"
    assert vms[0]["source_detail"] == "https://github.com/me/blog"


def test_template_vm_reports_its_template():
    vms = _enrich([{"name": "graf"}], rows=[_row(1, "graf", template="grafana")])
    assert (vms[0]["source"], vms[0]["source_detail"]) == ("Шаблон", "grafana")


def test_cluster_vm_reports_the_cluster_name():
    vms = _enrich([{"name": "node-1"}], rows=[_row(1, "node-1", cluster_id=5)],
                  clusters=[types.SimpleNamespace(id=5, name="lab")])
    assert (vms[0]["source"], vms[0]["source_detail"]) == ("Кластер", "lab")


def test_plain_vm_says_so_instead_of_leaving_the_field_empty():
    """Пустая строка в фильтре выглядела бы как «источник неизвестен»."""
    vms = _enrich([{"name": "plain"}], rows=[_row(1, "plain")])
    assert vms[0]["source"] == "Чистая ОС"


def test_deployment_wins_over_the_template_field():
    """У приложения маркетплейса шаблон не задан, но если бы задали — важнее
    то, чем машина является для пользователя."""
    vms = _enrich([{"name": "app"}], rows=[_row(1, "app", template="docker")],
                  deps=[_dep(7, 1, "marketplace", "marketplace://ghost")])
    assert vms[0]["source"] == "Маркетплейс"


# --------------------------------- домены ------------------------------------

def test_domain_bound_to_the_vm_is_listed():
    vms = _enrich([{"name": "a"}], rows=[_row(1, "a")],
                  domains=[_dom("vm", 1, "a.example.com")])
    assert vms[0]["domains"] == ["a.example.com"]


def test_domain_bound_to_the_deployment_lands_on_its_vm():
    """Маркетплейс создаёт и ВМ, и деплой, поэтому домен часто привязан ко
    второму — искать его надо всё равно по машине."""
    vms = _enrich([{"name": "n8n-1"}], rows=[_row(1, "n8n-1")],
                  deps=[_dep(7, 1, "marketplace", "marketplace://n8n")],
                  domains=[_dom("deployment", 7, "n8n.example.com")])
    assert vms[0]["domains"] == ["n8n.example.com"]


def test_someone_elses_domain_does_not_leak_onto_the_vm():
    vms = _enrich([{"name": "a"}], rows=[_row(1, "a")],
                  domains=[_dom("vm", 99, "other.example.com")])
    assert vms[0]["domains"] == []


def test_vm_without_domains_gets_an_empty_list_not_missing_key():
    """Фронт разворачивает это поле в поиск через spread — None там уронил бы
    весь список."""
    vms = _enrich([{"name": "a"}], rows=[_row(1, "a")])
    assert vms[0]["domains"] == []


# ------------------------------- стоимость -----------------------------------

def test_enrichment_does_not_query_per_vm():
    """Список открывают часто: N+1 здесь стоил бы дороже самой выборки."""
    db = FakeDb(rows=[_row(i, f"vm{i}") for i in range(1, 21)])
    _enrich_for_filters(db, [{"name": f"vm{i}"} for i in range(1, 21)])
    assert db.queries <= 4, f"запросов: {db.queries} — похоже на N+1"


def test_vm_missing_from_the_database_is_left_alone():
    """ВМ может существовать в кластере без записи в БД — она просто не
    получает полей фильтра, а не роняет обработку остальных."""
    vms = _enrich([{"name": "ghost-vm"}, {"name": "known"}], rows=[_row(1, "known")])
    assert "source" not in vms[0]
    assert vms[1]["source"] == "Чистая ОС"


# ------------------------- фильтр по владельцу — только админу ---------------

def test_owner_filter_is_admin_only():
    """У студента чужих ВМ в списке и так нет (list_vms их не отдаёт), а поле
    «Владелец» создавало бы впечатление, что бывают."""
    import re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "App.jsx"), encoding="utf-8") as f:
        src = f.read()

    i = src.index('<label className="input-label">Владелец</label>')
    # Поле обёрнуто в проверку роли — ищем её в ближайшем блоке выше.
    assert "userRole === 'admin'" in src[i - 300:i]


def test_search_covers_the_fields_the_backend_added():
    """Смысл enrich'а — искать по домену и источнику, которых в карточке не
    видно. Если поиск их не читает, поля добавлены впустую."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "App.jsx"), encoding="utf-8") as f:
        src = f.read()

    block = src[src.index("const matchesVmFilter"):]
    block = block[:block.index("};")]
    for field in ("vm.name", "vm.owner_username", "vm.source", "vm.source_detail",
                  "vm.domains", "vm.ips", "vm.cluster_name"):
        assert field in block, field


def test_filter_panel_is_not_hidden_on_a_small_list():
    """Сначала панель пряталась при одной машине как «лишний шум». Но тогда
    её не найти и в тот момент, когда она понадобится: вкладка выглядит так,
    будто поиска в ней нет вовсе. Выпадающие списки сами скрываются, пока
    значение в них одно, поэтому на одной ВМ остаётся только строка поиска —
    и этого достаточно."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "App.jsx"), encoding="utf-8") as f:
        src = f.read()
    assert "(vms.length + externalServers.length) > 0 &&" in src
    assert "(vms.length + externalServers.length) > 1 &&" not in src
