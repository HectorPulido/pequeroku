"""Tests for the read-only ssh_port collision forensic scan."""

import io
import json

import pytest
from django.core.management import call_command

from vm_manager.models import Container
from vm_manager.test_utils import create_container, create_node, create_user

pytestmark = pytest.mark.django_db


class _FakeScanClient:
    """Returns a preset list_vms per node; records that it was read-only."""

    vms_by_node: dict = {}

    def __init__(self, node, *a, **k):
        self.node = node

    def list_vms(self):
        return _FakeScanClient.vms_by_node.get(self.node.pk, [])


def _patch(monkeypatch, vms_by_node):
    _FakeScanClient.vms_by_node = vms_by_node
    monkeypatch.setattr(
        "vm_manager.management.commands.scan_collisions.VMServiceClient",
        _FakeScanClient,
    )


def _run_json(**opts):
    out = io.StringIO()
    call_command("scan_collisions", "--json", stdout=out, **opts)
    return json.loads(out.getvalue())


def test_detects_two_containers_on_one_port(monkeypatch):
    node = create_node()
    a = create_container(user=create_user("owner-a"), node=node, container_id="vm-a")
    b = create_container(user=create_user("owner-b"), node=node, container_id="vm-b")
    _patch(
        monkeypatch,
        {
            node.pk: [
                {"id": "vm-a", "ssh_port": 5001, "state": "running"},
                {"id": "vm-b", "ssh_port": 5001, "state": "running"},
            ]
        },
    )

    report = _run_json()

    assert len(report["collisions"]) == 1
    col = report["collisions"][0]
    assert col["ssh_port"] == 5001
    assert col["count"] == 2
    pks = {m["container_pk"] for m in col["members"]}
    assert pks == {a.pk, b.pk}


def test_no_collision_when_ports_distinct(monkeypatch):
    node = create_node()
    create_container(user=create_user("owner-a"), node=node, container_id="vm-a")
    create_container(user=create_user("owner-b"), node=node, container_id="vm-b")
    _patch(
        monkeypatch,
        {
            node.pk: [
                {"id": "vm-a", "ssh_port": 5001, "state": "running"},
                {"id": "vm-b", "ssh_port": 5002, "state": "running"},
            ]
        },
    )

    report = _run_json()

    assert report["collisions"] == []


def test_stopped_vms_do_not_count_as_collision(monkeypatch):
    node = create_node()
    create_container(user=create_user("owner-a"), node=node, container_id="vm-a")
    create_container(user=create_user("owner-b"), node=node, container_id="vm-b")
    # Same port but one is stopped -> only one live answerer, no collision.
    _patch(
        monkeypatch,
        {
            node.pk: [
                {"id": "vm-a", "ssh_port": 5001, "state": "running"},
                {"id": "vm-b", "ssh_port": 5001, "state": "stopped"},
            ]
        },
    )

    report = _run_json()

    assert report["collisions"] == []


def test_reports_leaked_node_vm(monkeypatch):
    node = create_node()
    # A node VM with no Container row.
    _patch(
        monkeypatch,
        {node.pk: [{"id": "ghost", "ssh_port": 5001, "state": "running"}]},
    )

    report = _run_json()

    assert any(lk["vm_id"] == "ghost" for lk in report["leaks"])
