"""
Warm pool of pre-booted VMs.

Booting QEMU and waiting for SSH (``vm_service``) is the slow part of creating a
container (~10s on KVM, much more on TCG). To make creation feel instant we keep a
few VMs of the common types already booted and SSH-ready, owned by a dedicated
system user (``__pool__``) and flagged ``is_pool=True``. When a user creates a
container we atomically claim one of those warm VMs and re-assign it to them — a
plain DB row update, no QEMU work on the hot path.

Heavy types are never pre-built: a type is only warmed when
``poolable and pool_target > 0`` (see ``ContainerType``).

Everything here lives in ``web_service``; ``vm_service`` and the golden image are
untouched. Warm VMs are ordinary ``Container`` rows, so the reconciler keeps them
alive and capacity/credit accounting already treats them correctly (they reserve
node capacity via ``desired_state="running"`` but consume no real user's credits
until claimed).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Container, ContainerType, Node
from .vm_client import VMServiceClient, VMCreate

# System user that owns unclaimed warm-pool VMs.
POOL_USERNAME = "__pool__"


def get_pool_user():
    """Return (creating if needed) the system user that owns warm-pool VMs."""
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=POOL_USERNAME,
        defaults={"is_active": False},
    )
    return user


def provision_container(
    node: Node,
    ct: ContainerType,
    *,
    user,
    is_pool: bool,
    name: str | None = None,
) -> Container:
    """
    Boot a brand-new VM on ``node`` for container type ``ct`` and persist its row.

    Shared by the warm-pool replenisher (``is_pool=True``, owned by the pool user)
    and the on-demand fallback path. ``Container.save()`` derives memory/vcpus/disk
    from ``ct`` and the resource quota from ``user``.
    """
    service = VMServiceClient(node)
    vm = service.create_vm(
        VMCreate(
            vcpus=int(ct.vcpus),
            mem_mib=int(ct.memory_mb),
            disk_gib=int(ct.disk_gib),
        )
    )
    return Container.objects.create(
        name=name or "",
        user=user,
        container_id=vm["id"],
        base_image="",
        status="creating",
        memory_mb=int(ct.memory_mb),
        vcpus=int(ct.vcpus),
        disk_gib=int(ct.disk_gib),
        node=node,
        container_type=ct,
        is_pool=is_pool,
    )


def claim_warm_container(
    *,
    user,
    ct: ContainerType,
    candidate_nodes: list[Node],
    name: str | None = None,
) -> Container | None:
    """
    Atomically claim a ready warm VM of type ``ct`` and hand it to ``user``.

    Returns the claimed ``Container`` (now owned by ``user``, ``is_pool=False``), or
    ``None`` if no ready warm VM is available — in which case the caller falls back
    to booting one on demand.

    Concurrency-safe on PostgreSQL via ``select_for_update(skip_locked=True)``: two
    simultaneous creates never grab the same VM, and a locked row is skipped rather
    than waited on. On backends without row locking (e.g. SQLite in tests) the clause
    is a no-op, which is fine for single-threaded test runs.
    """
    node_ids = [n.pk for n in candidate_nodes]
    if not node_ids:
        return None

    with transaction.atomic():
        warm = (
            Container.objects.select_for_update(skip_locked=True)
            .filter(
                is_pool=True,
                status=Container.Status.RUNNING,
                container_type=ct,
                node_id__in=node_ids,
            )
            .order_by("created_at")
            .first()
        )
        if warm is None:
            return None

        warm.is_pool = False
        warm.user = user
        if name:
            warm.name = name
        warm.save()
        return warm


def warm_count(node: Node, ct: ContainerType) -> int:
    """Warm VMs of ``ct`` currently on ``node`` (any status, so in-flight ones count)."""
    return Container.objects.filter(is_pool=True, node=node, container_type=ct).count()


def replenish_pools(nodes: list[Node]) -> int:
    """
    Top up each poolable type on each node up to its ``pool_target``, respecting
    free node capacity. Returns how many warm VMs were provisioned.
    """
    pool_user = get_pool_user()
    types = list(ContainerType.objects.filter(poolable=True, pool_target__gt=0))
    provisioned = 0

    for node in nodes:
        for ct in types:
            deficit = int(ct.pool_target) - warm_count(node, ct)
            for _ in range(max(deficit, 0)):
                free_v, free_m = node.get_free_resources()
                if free_v < int(ct.vcpus) or free_m < int(ct.memory_mb):
                    break  # node is full for this type; stop topping it up
                try:
                    provision_container(node, ct, user=pool_user, is_pool=True)
                    provisioned += 1
                except Exception:
                    # Node/service trouble; give up on this type and retry next pass.
                    break
    return provisioned


def trim_pools(nodes: list[Node]) -> int:
    """
    Destroy surplus warm VMs: anything beyond ``pool_target`` per type, and every
    warm VM of a now non-poolable type. Returns how many were destroyed.
    """
    allowed_by_type = {
        ct.pk: (int(ct.pool_target) if ct.poolable else 0)
        for ct in ContainerType.objects.all()
    }
    trimmed = 0

    for node in nodes:
        warm = list(
            Container.objects.filter(is_pool=True, node=node).order_by("-created_at")
        )
        by_type: dict[int | None, list[Container]] = {}
        for c in warm:
            by_type.setdefault(c.container_type_id, []).append(c)

        for ct_id, rows in by_type.items():
            allowed = allowed_by_type.get(ct_id, 0) if ct_id is not None else 0
            surplus = rows[: max(len(rows) - allowed, 0)]
            for c in surplus:
                if _destroy_warm(c):
                    trimmed += 1
    return trimmed


def _destroy_warm(c: Container) -> bool:
    """Best-effort delete of a warm VM on its node, then drop the row."""
    try:
        VMServiceClient(c.node).delete_vm(c.container_id)
    except Exception:
        # The row goes away regardless; a leaked VM is reconciled/cleaned later.
        pass
    try:
        c.delete()
        return True
    except Exception:
        return False
