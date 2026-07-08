import io

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from vm_manager import pool
from vm_manager.models import Container, ContainerType, ResourceQuota
from vm_manager.test_utils import (
    create_container,
    create_node,
    create_quota,
    create_user,
)

pytestmark = pytest.mark.django_db


class FakeVMClient:
    """Records create/delete calls; never touches the network."""

    created = []
    deleted = []
    _counter = 0

    def __init__(self, node, *args, **kwargs):
        self.node = node

    @classmethod
    def reset(cls):
        cls.created = []
        cls.deleted = []
        cls._counter = 0

    def create_vm(self, payload):
        FakeVMClient._counter += 1
        vid = f"warm-{FakeVMClient._counter}"
        FakeVMClient.created.append((self.node.pk, vid))
        return {"id": vid}

    def delete_vm(self, vm_id):
        FakeVMClient.deleted.append(vm_id)
        return {"status": "deleted"}

    def refresh_health(self):
        # Stand in for a reachable node: keep it healthy so it stays a
        # scheduling candidate (the real client would ping /health over HTTP).
        self.node.healthy = True
        self.node.save(update_fields=["healthy"])
        return True


@pytest.fixture
def fake_vm(monkeypatch):
    FakeVMClient.reset()
    for target in (
        "vm_manager.pool.VMServiceClient",
        "vm_manager.views.VMServiceClient",
        "vm_manager.mixin.VMServiceClient",
        "vm_manager.orchestration.VMServiceClient",
        "vm_manager.templates.VMServiceClient",
        "vm_manager.management.commands.prewarm_pool.VMServiceClient",
    ):
        monkeypatch.setattr(target, FakeVMClient, raising=False)
    monkeypatch.setattr("vm_manager.views.audit_log_http", lambda *a, **k: None)
    # Always read quota fresh from the DB to avoid stale OneToOne cache in tests.
    monkeypatch.setattr(
        "vm_manager.views.ContainersViewSet._check_quota",
        lambda self, request: ResourceQuota.objects.filter(
            user=request.user, active=True
        ).first(),
        raising=False,
    )
    return FakeVMClient


def _poolable_type(name="pool-small", target=2, **kwargs):
    defaults = dict(
        container_type_name=name,
        memory_mb=1024,
        vcpus=1,
        disk_gib=5,
        credits_cost=1,
        poolable=True,
        pool_target=target,
    )
    defaults.update(kwargs)
    return ContainerType.objects.create(**defaults)


def _make_warm(node, ct, status=Container.Status.RUNNING, container_id="warm-x"):
    return Container.objects.create(
        user=pool.get_pool_user(),
        node=node,
        container_id=container_id,
        container_type=ct,
        is_pool=True,
        status=status,
    )


# --------------------------------------------------------------------------- #
# claim_warm_container
# --------------------------------------------------------------------------- #
def test_claim_reassigns_a_ready_warm_vm(fake_vm):
    node = create_node()
    ct = _poolable_type()
    warm = _make_warm(node, ct, container_id="warm-ready")
    alice = create_user("alice")
    create_quota(user=alice)

    claimed = pool.claim_warm_container(user=alice, ct=ct, candidate_nodes=[node])

    assert claimed is not None
    assert claimed.pk == warm.pk
    assert claimed.is_pool is False
    assert claimed.user_id == alice.pk
    # No VM was booted: claiming is a pure DB re-assignment.
    assert FakeVMClient.created == []

    warm.refresh_from_db()
    assert warm.is_pool is False
    assert warm.user_id == alice.pk


def test_claim_returns_none_when_pool_empty(fake_vm):
    node = create_node()
    ct = _poolable_type()
    alice = create_user("alice")
    create_quota(user=alice)

    assert pool.claim_warm_container(user=alice, ct=ct, candidate_nodes=[node]) is None


def test_claim_skips_warm_vms_still_booting(fake_vm):
    node = create_node()
    ct = _poolable_type()
    _make_warm(node, ct, status="creating", container_id="warm-booting")
    alice = create_user("alice")
    create_quota(user=alice)

    # Only 'running' warm VMs are claimable; a still-provisioning one is skipped.
    assert pool.claim_warm_container(user=alice, ct=ct, candidate_nodes=[node]) is None


def test_claim_only_matches_requested_type_and_candidate_nodes(fake_vm):
    node = create_node()
    other_node = create_node(name="node-2")
    ct = _poolable_type(name="pool-a")
    other_ct = _poolable_type(name="pool-b")
    alice = create_user("alice")
    create_quota(user=alice)

    _make_warm(node, other_ct, container_id="warm-othertype")
    _make_warm(other_node, ct, container_id="warm-othernode")

    # Wrong type on the candidate node, and right type on a non-candidate node.
    assert pool.claim_warm_container(user=alice, ct=ct, candidate_nodes=[node]) is None


def test_two_sequential_claims_do_not_return_the_same_vm(fake_vm):
    node = create_node()
    ct = _poolable_type()
    _make_warm(node, ct, container_id="warm-1")
    a = create_user("a")
    b = create_user("b")
    create_quota(user=a)
    create_quota(user=b)

    first = pool.claim_warm_container(user=a, ct=ct, candidate_nodes=[node])
    second = pool.claim_warm_container(user=b, ct=ct, candidate_nodes=[node])

    assert first is not None
    assert second is None  # only one warm VM existed


def test_warm_vms_invisible_and_credit_free_for_users(fake_vm):
    node = create_node()
    ct = _poolable_type()
    _make_warm(node, ct, container_id="warm-hidden")
    alice = create_user("alice")
    create_quota(user=alice)

    assert Container.visible_containers_for(alice).count() == 0
    assert alice.quota.calculate_used_credits(alice) == 0


# --------------------------------------------------------------------------- #
# replenish_pools / trim_pools
# --------------------------------------------------------------------------- #
def test_replenish_respects_target_and_capacity(fake_vm):
    # Neutralize seeded types so only our type drives provisioning.
    ContainerType.objects.update(poolable=False, pool_target=0)
    node = create_node(capacity_vcpus=2, capacity_mem_mb=2048)
    ct = _poolable_type(target=5)  # 1 vCPU / 1024 MB each

    provisioned = pool.replenish_pools([node])

    # Node fits only 2 (2 vCPU / 2048 MB), even though pool_target is 5.
    assert provisioned == 2
    assert len(FakeVMClient.created) == 2
    assert Container.objects.filter(is_pool=True, container_type=ct).count() == 2

    # Already at capacity: a second pass provisions nothing more.
    assert pool.replenish_pools([node]) == 0


def test_replenish_ignores_non_poolable_types(fake_vm):
    ContainerType.objects.update(poolable=False, pool_target=0)
    node = create_node(capacity_vcpus=8, capacity_mem_mb=8192)
    _poolable_type(name="heavy", poolable=False, pool_target=3)

    assert pool.replenish_pools([node]) == 0
    assert FakeVMClient.created == []


def test_trim_removes_surplus_warm_vms(fake_vm):
    node = create_node()
    ct = _poolable_type(target=1)
    for i in range(3):
        _make_warm(node, ct, container_id=f"warm-{i}")

    trimmed = pool.trim_pools([node])

    assert trimmed == 2
    assert Container.objects.filter(is_pool=True, container_type=ct).count() == 1
    assert len(FakeVMClient.deleted) == 2


def test_trim_removes_all_warm_vms_of_non_poolable_type(fake_vm):
    node = create_node()
    ct = _poolable_type(name="now-heavy", target=0, poolable=False)
    for i in range(2):
        _make_warm(node, ct, container_id=f"warm-{i}")

    trimmed = pool.trim_pools([node])

    assert trimmed == 2
    assert Container.objects.filter(is_pool=True, container_type=ct).count() == 0


def test_destroy_warm_skips_a_row_claimed_after_snapshot(fake_vm):
    """The trim race: a warm row claimed between trim's snapshot and _destroy_warm
    must NOT be destroyed — that would wipe a live user's VM and disk."""
    node = create_node()
    ct = _poolable_type()
    warm = _make_warm(node, ct, container_id="warm-claimed-race")

    # trim_pools snapshotted this row while it was still a pool VM.
    stale_snapshot = Container.objects.get(pk=warm.pk)

    # Meanwhile a real user claims it (is_pool -> False).
    warm.is_pool = False
    warm.user = create_user("racer")
    warm.save()

    # trim now acts on its stale snapshot: it must re-check and skip.
    destroyed = pool._destroy_warm(stale_snapshot)

    assert destroyed is False
    assert FakeVMClient.deleted == []  # the node VM (and its disk) was never touched
    assert Container.objects.filter(pk=warm.pk).exists()  # the row survives


def test_destroy_warm_deletes_a_genuine_pool_row(fake_vm):
    """Regression: a row that is still is_pool=True is destroyed as before."""
    node = create_node()
    ct = _poolable_type()
    warm = _make_warm(node, ct, container_id="warm-genuine")

    destroyed = pool._destroy_warm(warm)

    assert destroyed is True
    assert FakeVMClient.deleted == ["warm-genuine"]
    assert not Container.objects.filter(pk=warm.pk).exists()


# --------------------------------------------------------------------------- #
# create() endpoint integration
# --------------------------------------------------------------------------- #
def _authed_user_for(ct, username, credits=5):
    user = create_user(username)
    create_quota(user=user, credits=credits)
    user.refresh_from_db()
    user.quota.allowed_types.set([ct.id])
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def test_create_claims_from_pool_without_booting(fake_vm):
    node = create_node()
    ct = _poolable_type()
    warm = _make_warm(node, ct, container_id="warm-claimed")
    user, client = _authed_user_for(ct, "creator")

    res = client.post(
        reverse("container-list"), data={"container_type": ct.id}, format="json"
    )
    assert res.status_code == 201, res.content

    data = res.json()
    assert data["id"] == warm.pk
    # No new VM was booted on the hot path.
    assert FakeVMClient.created == []

    warm.refresh_from_db()
    assert warm.is_pool is False
    assert warm.user_id == user.pk


def test_create_falls_back_to_boot_when_pool_empty(fake_vm):
    node = create_node()
    ct = _poolable_type()  # poolable, but no warm stock provisioned
    user, client = _authed_user_for(ct, "creator2")

    res = client.post(
        reverse("container-list"), data={"container_type": ct.id}, format="json"
    )
    assert res.status_code == 201, res.content

    # Pool was empty -> the on-demand path booted exactly one VM.
    assert len(FakeVMClient.created) == 1
    obj = Container.objects.get(pk=res.json()["id"])
    assert obj.is_pool is False
    assert obj.user_id == user.pk
    assert obj.container_id.startswith("warm-")


# --------------------------------------------------------------------------- #
# prewarm_pool management command
# --------------------------------------------------------------------------- #
def test_prewarm_command_provisions_pool(fake_vm):
    ContainerType.objects.update(poolable=False, pool_target=0)
    node = create_node(capacity_vcpus=4, capacity_mem_mb=4096)
    ct = _poolable_type(target=2)

    out = io.StringIO()
    call_command("prewarm_pool", stdout=out)

    assert "[prewarm]" in out.getvalue()
    assert Container.objects.filter(is_pool=True, container_type=ct).count() == 2
    assert len(FakeVMClient.created) == 2


# --------------------------------------------------------------------------- #
# warm VMs are hidden from the user-facing API
# --------------------------------------------------------------------------- #
def test_pool_vms_hidden_from_list_api(fake_vm):
    node = create_node()
    ct = _poolable_type()
    _make_warm(node, ct, container_id="warm-hidden-api")

    owner = create_user("viewer")
    create_quota(user=owner)
    own = create_container(
        user=owner, node=node, container_id="own-1", container_type=ct
    )
    pool_ids = set(Container.objects.filter(is_pool=True).values_list("pk", flat=True))

    # Owner sees their own container, never the warm pool.
    client = APIClient()
    client.force_authenticate(user=owner)
    own_ids = {c["id"] for c in client.get(reverse("container-list")).json()}
    assert own.pk in own_ids
    assert not (pool_ids & own_ids)

    # Superuser sees everything except the warm pool.
    su = create_user("root", is_superuser=True)
    sclient = APIClient()
    sclient.force_authenticate(user=su)
    su_ids = {c["id"] for c in sclient.get(reverse("container-list")).json()}
    assert own.pk in su_ids
    assert not (pool_ids & su_ids)
