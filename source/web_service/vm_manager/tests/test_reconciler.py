# Add tests for reconciler: batch reconciliation transitions, audit logs, dry-run behavior, and command handle flows
import io
import pytest
from django.core.management import call_command

from internal_config.models import AuditLog
from vm_manager.management.commands.reconcile_containers import Reconciler
from vm_manager.test_utils import (
    create_user,
    create_node,
    create_container,
)

pytestmark = pytest.mark.django_db


class FakeClient:
    def __init__(self):
        self.actions = []

    def action_vm(self, vm_id, action):
        # action is a VMAction instance, we only care about action.action
        act = getattr(action, "action", None)
        self.actions.append((vm_id, act))
        return {"ok": True}


class ErrorClient:
    def action_vm(self, vm_id, action):
        raise RuntimeError("boom")


def _make_two_containers_for_transitions():
    user = create_user(username="recon_user")
    node = create_node()
    # c1 should be started: desired running, currently stopped
    c1 = create_container(user=user, node=node, container_id="vm-1")
    c1.desired_state = "running"
    c1.status = "stopped"
    c1.save()

    # c2 should be stopped: desired stopped, currently running
    c2 = create_container(user=user, node=node, container_id="vm-2")
    c2.desired_state = "stopped"
    c2.status = "running"
    c2.save()

    return c1, c2


def test_reconcile_batch_transitions_and_audits(monkeypatch):
    c1, c2 = _make_two_containers_for_transitions()

    client = FakeClient()

    # Avoid external sync and vm-client instantiation
    monkeypatch.setattr(Reconciler, "_sync_statuses", lambda self, objs: [])
    monkeypatch.setattr(Reconciler, "_service_for", lambda self, c: client)

    r = Reconciler(stdout=io.StringIO(), stderr=io.StringIO())
    actions, updated = r.reconcile_batch([c1, c2])

    assert actions == 2
    assert updated == 2

    # In-memory state transitions should be applied
    assert c1.status == "provisioning"
    assert c2.status == "stopped"

    # DB should be updated as well (bulk_update at the end)
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert c1.status == "provisioning"
    assert c2.status == "stopped"

    # Audits for both actions
    on_log = AuditLog.objects.filter(action="container.power_on").first()
    off_log = AuditLog.objects.filter(action="container.power_off").first()
    assert on_log is not None
    assert off_log is not None
    assert on_log.success is True
    assert off_log.success is True


def test_reconcile_batch_handles_action_error_audits_error(monkeypatch):
    user = create_user(username="recon_err_user")
    node = create_node()
    c = create_container(user=user, node=node, container_id="vm-err")
    c.desired_state = "running"
    c.status = "stopped"
    c.save()

    # No external sync
    monkeypatch.setattr(Reconciler, "_sync_statuses", lambda self, objs: [])
    # Client that raises on action
    monkeypatch.setattr(Reconciler, "_service_for", lambda self, c: ErrorClient())

    r = Reconciler(stdout=io.StringIO(), stderr=io.StringIO())
    actions, updated = r.reconcile_batch([c])

    assert actions == 0
    assert updated == 0

    log = AuditLog.objects.filter(action="container.real_status").first()
    assert log is not None
    assert log.success is False
    assert isinstance(log.metadata, dict)
    assert log.metadata.get("container_id") == "vm-err"
    assert log.metadata.get("desired") == "running"
    assert log.metadata.get("status") == "stopped"


def test_command_dry_run_counts_actions_without_updates(monkeypatch, capsys):
    c1, c2 = _make_two_containers_for_transitions()

    # Ensure reconcile does not call any external sync in dry-run
    monkeypatch.setattr(Reconciler, "_sync_statuses", lambda self, objs: [])

    # Run management command with dry-run
    call_command("reconcile_containers", "--dry-run")

    out = capsys.readouterr().out
    assert "[reconciler]" in out
    assert "actions=2" in out
    assert "local_updates=0" in out

    # Ensure DB statuses remain unchanged (no updates in dry run)
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert c1.status == "stopped"
    assert c2.status == "running"


def test_command_with_container_ids_executes_only_one(monkeypatch, capsys):
    user = create_user(username="recon_one_user")
    node = create_node()
    c = create_container(user=user, node=node, container_id="vm-one")
    c.desired_state = "running"
    c.status = "stopped"
    c.save()

    client = FakeClient()
    monkeypatch.setattr(Reconciler, "_sync_statuses", lambda self, objs: [])
    monkeypatch.setattr(Reconciler, "_service_for", lambda self, obj: client)

    call_command("reconcile_containers", "--container-ids", str(c.pk))

    out = capsys.readouterr().out
    # Should mention container mode, and one action/update
    assert "container_id=" in out
    assert "actions=1" in out
    assert "local_updates=1" in out

    # Audit recorded
    log = AuditLog.objects.filter(action="container.power_on").first()
    assert log is not None
    assert log.success is True

    # Status should have been updated in DB
    c.refresh_from_db()
    assert c.status == "provisioning"
