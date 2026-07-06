"""Framework-agnostic orchestration helpers.

The scheduling / quota / container-creation logic used to live inside
``VMSyncMixin`` (a DRF mixin) and the IDE's ``ContainersViewSet.create``. That
coupled it to ``self``/``request`` and made it unreachable from the public
``platform_api`` app without copy-paste. It now lives here as plain functions so
both the IDE viewset and the public API call the SAME code path. ``VMSyncMixin``
keeps thin methods that delegate here, preserving its existing behavior.

Nothing here depends on DRF; callers pass plain ``User``/``ContainerType``
objects. Models still live in ``vm_manager.models`` — this module is about logic,
not data.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from . import pool
from .models import Container, ContainerType, Node, ResourceQuota
from .vm_client import VMCreate, VMDuplicate, VMServiceClient

# Default output cap shared by the public API and the MCP server (256 KiB). Keeping
# it here means exec/runs and the MCP facade truncate identically.
DEFAULT_OUTPUT_LIMIT = 256 * 1024


class NoNodeAvailable(Exception):
    """No node — not even a best-effort random one — is available to place a VM."""


# --- Scheduling -------------------------------------------------------------


def candidate_nodes(heartbeat_ttl_s: int = 60) -> list[Node]:
    """Active, healthy nodes whose heartbeat is recent enough to schedule onto."""
    cutoff = timezone.now() - timedelta(seconds=heartbeat_ttl_s)
    return list(
        Node.objects.filter(active=True, healthy=True, heartbeat_at__gte=cutoff)
    )


def choose_node(
    needed_vcpus: int,
    needed_mem_mb: int,
    heartbeat_ttl_s: int = 3600,
) -> Node | None:
    """Best node by capacity score, or ``None`` if none can fit the request."""
    best: Node | None = None
    best_score = float("-inf")
    for n in candidate_nodes(heartbeat_ttl_s):
        free_v, free_m = n.get_free_resources()
        if free_v < int(needed_vcpus) or free_m < int(needed_mem_mb):
            continue
        score = n.get_node_score()
        if score > best_score:
            best = n
            best_score = score
    return best


def get_service_by_node(node: Node) -> VMServiceClient:
    return VMServiceClient(node, blocking=True)


def get_service(container: Container) -> VMServiceClient:
    return VMServiceClient(container.node, blocking=True)


# --- Quota ------------------------------------------------------------------


def check_quota(user: User) -> ResourceQuota | None:
    """Return the user's quota if it exists and is active, else ``None``."""
    quota = getattr(user, "quota", None)
    if not quota or not quota.active:
        return None
    return quota


# --- Container creation -----------------------------------------------------


def claim_or_create_container(
    *,
    user: User,
    ct: ContainerType,
    name: str | None = None,
    expires_at=None,
) -> tuple[Container, str | None, bool]:
    """Hand ``user`` a container of type ``ct``.

    Fast path: claim a pre-booted warm-pool VM if one of this type is ready (a
    plain DB re-assignment, no QEMU boot). Otherwise boot one on demand on the
    best node, falling back to a random node when none has spare capacity.

    Returns ``(container, warning, from_pool)``; ``warning`` is a non-fatal note
    (best-effort placement) or ``None``. Raises :class:`NoNodeAvailable` when not
    even a random node exists. ``expires_at`` (optional) marks the container for
    the TTL reaper; ``None`` means persistent.
    """
    claimed = pool.claim_warm_container(
        user=user,
        ct=ct,
        candidate_nodes=candidate_nodes(heartbeat_ttl_s=3600),
        name=name,
    )
    if claimed is not None:
        if expires_at is not None:
            claimed.expires_at = expires_at
            claimed.save(update_fields=["expires_at"])
        return claimed, None, True

    vcpus = int(ct.vcpus)
    mem_mb = int(ct.memory_mb)
    disk_gib = int(ct.disk_gib)

    node = choose_node(vcpus, mem_mb)
    warning: str | None = None
    if not node:
        node = Node.get_random_node()
        warning = (
            "No available nodes with enough capacity; proceeding on best-effort node"
        )
    if not node:
        raise NoNodeAvailable()

    service = VMServiceClient(node)
    vm = service.create_vm(VMCreate(vcpus=vcpus, mem_mib=mem_mb, disk_gib=disk_gib))
    c = Container.objects.create(
        name=name,
        user=user,
        container_id=vm["id"],
        status="creating",
        memory_mb=mem_mb,
        vcpus=vcpus,
        disk_gib=disk_gib,
        node=node,
        container_type=ct,
        expires_at=expires_at,
    )
    return c, warning, False


def duplicate_container(
    *,
    user: User,
    source: Container,
    name: str | None = None,
) -> tuple[Container, str | None]:
    """Clone ``source`` into a new container owned by ``user``.

    This is a disk-level duplicate: the vm-service copies the source VM's qcow2
    overlay into a fresh VM, so the copy boots with identical data. Because the
    disk lives on the source's node, the duplicate is always placed on that SAME
    node (cross-node cloning is not supported here) and the warm pool is bypassed
    (a clone must copy a specific source disk, not a generic pool VM).

    The source VM must be stopped — the node refuses (409) otherwise. Callers are
    responsible for quota checks. Returns ``(container, warning)``; raises
    :class:`NoNodeAvailable` if the source has no node.
    """
    node = source.node
    if node is None:
        raise NoNodeAvailable()

    ct = source.container_type
    vcpus = int(ct.vcpus) if ct else int(source.vcpus)
    mem_mb = int(ct.memory_mb) if ct else int(source.memory_mb)
    disk_gib = int(ct.disk_gib) if ct else int(source.disk_gib)

    service = VMServiceClient(node)
    vm = service.duplicate_vm(
        str(source.container_id),
        VMDuplicate(vcpus=vcpus, mem_mib=mem_mb, disk_gib=disk_gib, start=True),
    )
    c = Container.objects.create(
        name=name,
        user=user,
        container_id=vm["id"],
        status="creating",
        memory_mb=mem_mb,
        vcpus=vcpus,
        disk_gib=disk_gib,
        node=node,
        container_type=ct,
        # The clone already carries the source's full disk, so skip the
        # first-connect "default" template that fresh VMs get.
        first_start=False,
    )
    return c, None


# --- Output handling --------------------------------------------------------


def truncate_output(text: str, limit: int = DEFAULT_OUTPUT_LIMIT) -> tuple[str, bool]:
    """Cap ``text`` at ``limit`` bytes (UTF-8). Returns ``(text, truncated)``.

    Truncation is byte-accurate (keeps the tail of multibyte chars valid) so
    HTTP payloads and LLM context stay bounded.
    """
    if text is None:
        return "", False
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    clipped = encoded[:limit].decode("utf-8", errors="ignore")
    return clipped, True
