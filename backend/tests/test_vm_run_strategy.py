"""Статус ВМ после S3-отката должен учитывать runStrategy, а не только running."""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException

from app.core.k8s_client import K8sClient


@pytest.fixture
def parser(monkeypatch):
    client = K8sClient.__new__(K8sClient)
    def no_secret(*args):
        raise ApiException(status=404)
    client.core_api = NS(read_namespaced_secret=no_secret,
                         list_namespaced_pod=lambda **kwargs: NS(items=[]))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    return client._parse_vm_object


@pytest.mark.parametrize("strategy", ["Always", "RerunOnFailure", "Once", "Manual"])
def test_running_instance_is_not_stopping_when_running_field_is_absent(parser, strategy):
    vm = {"metadata": {"name": "vm1", "namespace": "default"},
          "spec": {"runStrategy": strategy}}
    vmi = {"metadata": {}, "status": {"phase": "Running"}}
    result = parser(vm, vmi)
    assert result["status"] == "Running"
    assert result["desired_state"] == "Running"


@pytest.mark.parametrize("strategy", ["Always", "RerunOnFailure", "Once"])
def test_automatic_strategy_without_instance_is_starting(parser, strategy):
    result = parser({"metadata": {"name": "vm1", "namespace": "default"},
                     "spec": {"runStrategy": strategy}})
    assert result["status"] == "Starting"


@pytest.mark.parametrize("spec", [{"running": False}, {"runStrategy": "Halted"}])
def test_halted_vm_with_remaining_instance_is_stopping(parser, spec):
    result = parser({"metadata": {"name": "vm1", "namespace": "default"}, "spec": spec},
                    {"metadata": {}, "status": {"phase": "Running"}})
    assert result["status"] == "Stopping"
    assert result["desired_state"] == "Stopped"


def test_manual_vm_without_instance_stays_stopped(parser):
    result = parser({"metadata": {"name": "vm1", "namespace": "default"},
                     "spec": {"runStrategy": "Manual"}})
    assert result["status"] == "Stopped"


def test_deleting_instance_is_stopping_even_with_always_strategy(parser):
    result = parser({"metadata": {"name": "vm1", "namespace": "default"},
                     "spec": {"runStrategy": "Always"}},
                    {"metadata": {"deletionTimestamp": "2026-10-08T10:00:00Z"},
                     "status": {"phase": "Running"}})
    assert result["status"] == "Stopping"


def test_legacy_running_field_still_works(parser):
    result = parser({"metadata": {"name": "vm1", "namespace": "default"},
                     "spec": {"running": True}},
                    {"metadata": {}, "status": {"phase": "Running"}})
    assert result["status"] == "Running"
