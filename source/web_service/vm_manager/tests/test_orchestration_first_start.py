"""``claim_or_create_container`` and the ``first_start`` welcome-seed flag.

The flag is what arms the one-time "default" template seed applied on the first
IDE connect (``templates.first_start_of_container``). The IDE wants it armed for
fresh workspaces; the API / MCP / ephemeral runs opt out so the seed never runs
against a workspace they populated programmatically. These tests pin that both
creation branches (on-demand boot and warm-pool claim) honor the opt-out.
"""

from __future__ import annotations

import pytest

from vm_manager import orchestration
from vm_manager.models import Container
from vm_manager.test_utils import (
    create_container,
    create_container_type,
    create_node,
    create_quota,
    create_user,
)


class _FakeVMClient:
    def __init__(self, node, *args, **kwargs):
        self.node = node

    def create_vm(self, payload):
        return {"id": "vm-fresh-1"}


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    monkeypatch.setattr(orchestration, "VMServiceClient", _FakeVMClient, raising=False)


def _user_ct():
    node = create_node()
    ct = create_container_type(container_type_name="small", memory_mb=256, vcpus=1)
    user = create_user("orch-user")
    create_quota(user=user, allowed_types=[ct])
    return node, user, ct


@pytest.mark.django_db
def test_on_demand_default_keeps_first_start_true():
    _node, user, ct = _user_ct()
    c, _warn, from_pool = orchestration.claim_or_create_container(user=user, ct=ct)
    assert from_pool is False
    assert c.first_start is True


@pytest.mark.django_db
def test_on_demand_opt_out_clears_first_start():
    _node, user, ct = _user_ct()
    c, _warn, from_pool = orchestration.claim_or_create_container(
        user=user, ct=ct, first_start=False
    )
    assert from_pool is False
    assert c.first_start is False


@pytest.mark.django_db
def test_pool_claim_opt_out_clears_first_start():
    from vm_manager.pool import get_pool_user

    node, user, ct = _user_ct()
    pool_user = get_pool_user()
    warm = create_container(
        user=pool_user,
        node=node,
        container_type=ct,
        status=Container.Status.RUNNING,
        is_pool=True,
        first_start=True,
    )

    c, _warn, from_pool = orchestration.claim_or_create_container(
        user=user, ct=ct, name="claimed", first_start=False
    )

    assert from_pool is True
    assert c.pk == warm.pk
    c.refresh_from_db()
    assert c.first_start is False
    assert c.is_pool is False
    assert c.user == user
