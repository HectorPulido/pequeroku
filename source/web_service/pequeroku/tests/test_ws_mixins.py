"""Tests for the WebSocket mixins (pequeroku/mixins.py)."""

from __future__ import annotations

import json

import pytest

from pequeroku.mixins import WSBaseUtilsMixin, ContainerAccessMixin, AuditMixin
from vm_manager.test_utils import create_user, create_container


# --------------------------------------------------------------------------- #
# WSBaseUtilsMixin
# --------------------------------------------------------------------------- #
def test_ws_client_ip_variants():
    m = WSBaseUtilsMixin()
    assert m._ws_client_ip(None) == ""
    assert m._ws_client_ip({"client": ("1.2.3.4", 5555)}) == "1.2.3.4"
    assert m._ws_client_ip({}) == ""  # no client key -> default (None,) -> ""


def test_ws_user_agent_variants():
    m = WSBaseUtilsMixin()
    assert m._ws_user_agent(None) == ""
    scope = {"headers": [(b"host", b"x"), (b"user-agent", b"Mozilla/5.0")]}
    assert m._ws_user_agent(scope) == "Mozilla/5.0"
    assert m._ws_user_agent({"headers": [(b"host", b"x")]}) == ""  # no UA header


async def test_send_json_safe_uses_send_without_ascii_escaping():
    sent = {}

    class C(WSBaseUtilsMixin):
        async def send(self, text_data=None):
            sent["text"] = text_data

    await C().send_json_safe({"msg": "ácentö"})
    # ensure_ascii=False keeps non-ASCII literal
    assert "ácentö" in sent["text"]
    assert json.loads(sent["text"]) == {"msg": "ácentö"}


async def test_send_json_safe_noop_without_send():
    # An object lacking `send` must not raise.
    await WSBaseUtilsMixin().send_json_safe({"a": 1})


# --------------------------------------------------------------------------- #
# ContainerAccessMixin (DB-backed)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db(transaction=True)
async def test_user_owns_container_superuser_always_true():
    from asgiref.sync import sync_to_async

    admin = await sync_to_async(create_user)(username="admin", is_superuser=True)
    # No container needed: superusers short-circuit to True.
    assert await ContainerAccessMixin._user_owns_container(123, admin.pk) is True


@pytest.mark.django_db(transaction=True)
async def test_get_container_simple_found_and_missing():
    from asgiref.sync import sync_to_async

    container = await sync_to_async(create_container)()
    found = await ContainerAccessMixin._get_container_simple(container.pk)
    assert found is not None and found.pk == container.pk
    assert await ContainerAccessMixin._get_container_simple(99999) is None


@pytest.mark.django_db(transaction=True)
async def test_get_container_with_node_found_and_missing():
    from asgiref.sync import sync_to_async

    container = await sync_to_async(create_container)()
    obj, node = await ContainerAccessMixin._get_container_with_node(
        container.pk, use_select_related=True
    )
    assert obj is not None and node is not None and node.pk == container.node.pk

    none_obj, none_node = await ContainerAccessMixin._get_container_with_node(99999)
    assert none_obj is None and none_node is None


# --------------------------------------------------------------------------- #
# AuditMixin
# --------------------------------------------------------------------------- #
async def test_audit_ws_forwards_to_audit_log(monkeypatch):
    captured = {}

    async def fake_audit_log_ws(**kwargs):
        captured.update(kwargs)
        return None

    import internal_config.audit as audit_mod

    monkeypatch.setattr(audit_mod, "audit_log_ws", fake_audit_log_ws)

    class C(AuditMixin):
        scope = {
            "client": ("9.9.9.9", 1),
            "headers": [(b"user-agent", b"UA/1")],
        }

    await C().audit_ws(
        action="container.read_file",
        user=None,
        target_type="container",
        target_id="vm-1",
        message="read",
        success=True,
        metadata={"k": "v"},
    )
    assert captured["action"] == "container.read_file"
    assert captured["ip"] == "9.9.9.9"
    assert captured["user_agent"] == "UA/1"
    assert captured["target_id"] == "vm-1"
    assert captured["metadata"] == {"k": "v"}
    assert captured["success"] is True
