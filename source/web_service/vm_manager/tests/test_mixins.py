import math
import pytest
from django.utils import timezone

from vm_manager.mixin import VMSyncMixin
from vm_manager.models import Node, Container

from vm_manager.test_utils import create_quota, create_user


pytestmark = pytest.mark.django_db

call_recorder = []


def fresh_node(
    name="node",
    host="http://127.0.0.1:8080",
    healthy=True,
    heartbeat=True,
    capacity_vcpus=8,
    capacity_mem_mb=8192,
):
    n = Node.objects.create(
        name=name,
        node_host=host,
        active=True,
        healthy=healthy,
        capacity_vcpus=capacity_vcpus,
        capacity_mem_mb=capacity_mem_mb,
    )
    if heartbeat:
        n.heartbeat_at = timezone.now()
        n.save(update_fields=["heartbeat_at"])
    return n


def running_container(user, node, vcpus=1, mem_mb=256, container_id="cid", name="c"):
    return Container.objects.create(
        user=user,
        node=node,
        container_id=container_id,
        name=name,
        base_image="",
        memory_mb=mem_mb,
        vcpus=vcpus,
        disk_gib=5,
        status=Container.Status.RUNNING,
        desired_state=Container.DesirableStatus.RUNNING,
    )


class DummyMixin(VMSyncMixin):
    def __init__(self, mapping_by_node=None, batch_size=None):
        # mapping_by_node: {Node -> {vm_id(str) -> state(str)}}
        self._mapping_by_node = mapping_by_node or {}
        if batch_size is not None:
            self.BATCH_SIZE = batch_size

    def _get_service_by_node(self, node: Node):
        mapping = self._mapping_by_node.get(node, {})

        class FakeClient:
            def __init__(self, mapping, rec):
                self.mapping = mapping
                self.rec = rec

            def get_vms(self, vm_ids):
                self.rec.append(list(vm_ids))
                # Return dict keyed by id as accepted by _index_vms_by_id
                return {
                    str(vmid): {
                        "id": str(vmid),
                        "state": self.mapping.get(str(vmid), "error"),
                    }
                    for vmid in vm_ids
                }

        return FakeClient(mapping, call_recorder)


def test_choose_node_picks_highest_score_node():
    """
    Given multiple eligible nodes, choose_node should return the one with highest score:
    score = 2*free_mem + 1*free_vcpus - 0.5*running_count
    """
    user = create_user("u1")

    # Node A: 4 vcpus, 4096 mem, no running containers
    node_a = fresh_node(name="A", capacity_vcpus=4, capacity_mem_mb=4096)

    # Node B: 8 vcpus, 2048 mem, no running containers
    node_b = fresh_node(name="B", capacity_vcpus=8, capacity_mem_mb=2048)

    # Node C: 6 vcpus, 8192 mem, but 1 running container consuming 4 vcpus / 4096 mem
    node_c = fresh_node(name="C", capacity_vcpus=6, capacity_mem_mb=8192)
    running_container(user, node_c, vcpus=4, mem_mb=4096, container_id="c1")

    mixin = VMSyncMixin()
    chosen = mixin.choose_node(needed_vcpus=2, needed_mem_mb=1024, heartbeat_ttl_s=3600)

    # node_a score = 2*4096 + 1*4 - 0.5*0 = 8196
    # node_b score = 2*2048 + 1*8 - 0.5*0 = 4104
    # node_c score = 2*4096 + 1*2 - 0.5*1 = 8193.5
    # Expect node A
    assert chosen == node_a


def test_choose_node_returns_none_when_no_capacity():
    """
    All nodes healthy/recent heartbeat but none meet required resources.
    """
    user = create_user("u2")

    # Single node with insufficient resources
    node_small = fresh_node(name="small", capacity_vcpus=1, capacity_mem_mb=512)
    # Even if it has no containers, it can't satisfy 2 vcpus / 1024 mem
    assert node_small.get_free_resources() == (1, 512)

    mixin = VMSyncMixin()
    chosen = mixin.choose_node(needed_vcpus=2, needed_mem_mb=1024, heartbeat_ttl_s=3600)
    assert chosen is None


def test_choose_node_ignores_unhealthy_or_old_heartbeat():
    """
    Nodes not healthy or with old heartbeat must be ignored.
    """
    # Old heartbeat node (healthy but heartbeat long ago)
    node_old = fresh_node(name="old", healthy=True, heartbeat=False)
    # Set a very old heartbeat
    node_old.heartbeat_at = timezone.now() - timezone.timedelta(hours=5)
    node_old.save(update_fields=["heartbeat_at"])

    # Unhealthy node with fresh heartbeat
    node_unhealthy = fresh_node(name="unhealthy", healthy=False, heartbeat=True)

    # Healthy and fresh
    node_ok = fresh_node(name="ok", healthy=True, heartbeat=True)

    mixin = VMSyncMixin()
    chosen = mixin.choose_node(needed_vcpus=1, needed_mem_mb=256, heartbeat_ttl_s=60)
    assert chosen == node_ok


def test_sync_statuses_updates_objects_and_batches_requests():
    """
    _sync_statuses should:
    - Group by node
    - Batch requests respecting BATCH_SIZE
    - Update object.status in memory and return the changed objects list
    """
    user = create_user("u3")
    node1 = fresh_node(name="node1")
    node2 = fresh_node(name="node2")

    # Create multiple containers per node, initial status = 'stopped' so changes are visible
    objs_node1 = [
        Container.objects.create(
            user=user,
            node=node1,
            container_id=f"n1-{i}",
            name=f"c1-{i}",
            base_image="",
            memory_mb=256,
            vcpus=1,
            disk_gib=5,
            status=Container.Status.STOPPED,
            desired_state=Container.DesirableStatus.RUNNING,
        )
        for i in range(5)
    ]
    objs_node2 = [
        Container.objects.create(
            user=user,
            node=node2,
            container_id=f"n2-{i}",
            name=f"c2-{i}",
            base_image="",
            memory_mb=256,
            vcpus=1,
            disk_gib=5,
            status=Container.Status.STOPPED,
            desired_state=Container.DesirableStatus.RUNNING,
        )
        for i in range(3)
    ]
    all_objs = objs_node1 + objs_node2

    # Define states: some running, some error (fake client returns "error" for unknown)
    states_node1 = {
        f"n1-{i}": ("running" if i % 2 == 0 else "stopped") for i in range(5)
    }
    # For node2, leave one id missing to force 'error'
    states_node2 = {
        "n2-0": "running",
        "n2-1": "running",
        # "n2-2" missing -> should become "error"
    }

    mixin = DummyMixin(
        mapping_by_node={node1: states_node1, node2: states_node2},
        batch_size=2,  # force batching
    )

    changed = mixin._sync_statuses(all_objs)

    # Expect all objects changed from 'stopped' to their new state except those that remain 'stopped'
    # Count how many should be "stopped" in node1 mapping: i odd indices -> 2 out of 5
    expected_stopped_ids = {f"n1-{i}" for i in range(5) if i % 2 == 1}
    # Others should be changed
    # For node2: n2-0, n2-1 -> running; n2-2 -> error
    # Summarize new status by id
    new_status = {o.container_id: o.status for o in all_objs}
    assert new_status["n2-0"] == "running"
    assert new_status["n2-1"] == "running"
    assert new_status["n2-2"] == "error"

    for i in range(5):
        cid = f"n1-{i}"
        if cid in expected_stopped_ids:
            assert new_status[cid] == "stopped"
        else:
            # either 'running' for even ids
            assert new_status[cid] == ("running" if i % 2 == 0 else "stopped")

    # changed list should include every object whose status changed compared to initial 'stopped'
    initially_stopped = {o.container_id for o in all_objs if o.status != "stopped"}
    # But we just updated statuses in memory; we need to recompute comparing originals:
    # Initially all were 'stopped'. Now, 'stopped' remain the same -> not changed.
    changed_ids = {o.container_id for o in changed}
    expect_changed_ids = {cid for cid, st in new_status.items() if st != "stopped"}
    assert changed_ids == expect_changed_ids

    # Verify batching: for node1 we have 5 ids -> ceil(5/2) = 3 calls; node2 3 ids -> ceil(3/2) = 2 calls
    # Total 5 calls
    print(len(call_recorder))
    assert len(call_recorder) == math.ceil(5 / 2) + math.ceil(3 / 2)
    # Each batch size should be <= 2
    assert all(len(batch) <= 2 for batch in call_recorder)


def test_sync_statuses_handles_empty_ids_gracefully():
    """
    If a container has empty/missing container_id, it should be skipped safely.
    """
    user = create_user("u4")
    node = fresh_node(name="single")
    good = Container.objects.create(
        user=user,
        node=node,
        container_id="ok-1",
        name="ok",
        base_image="",
        memory_mb=256,
        vcpus=1,
        disk_gib=5,
        status=Container.Status.STOPPED,
        desired_state=Container.DesirableStatus.RUNNING,
    )
    # Bad entry with empty container_id should be effectively ignored by batching
    bad = Container.objects.create(
        user=user,
        node=node,
        container_id="",
        name="bad",
        base_image="",
        memory_mb=256,
        vcpus=1,
        disk_gib=5,
        status=Container.Status.STOPPED,
        desired_state=Container.DesirableStatus.RUNNING,
    )

    mixin = DummyMixin(mapping_by_node={node: {"ok-1": "running"}})
    changed = mixin._sync_statuses([good, bad])

    # Only 'good' should change
    assert len(changed) == 1
    assert changed[0].pk == good.pk
    assert good.status == "running"
    # 'bad' remains untouched
    assert bad.status == "stopped"
