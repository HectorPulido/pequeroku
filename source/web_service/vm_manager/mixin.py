from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .models import Container, Node, ResourceQuota
from .vm_client import VMServiceClient, VMEnsure
from . import orchestration


class VMSyncMixin:
    """Thin DRF-facing wrapper over :mod:`vm_manager.orchestration`.

    The scheduling/quota/service helpers now live as pure functions in
    ``orchestration`` so the public ``platform_api`` app can reuse them. These
    methods just adapt ``self``/``request`` to those functions; the status-sync
    helpers below stay here because they're IDE-specific (bulk list refresh).
    """

    BATCH_SIZE: int = 100

    # Scheduler helpers (delegate to orchestration)
    def _candidate_nodes(self, heartbeat_ttl_s: int = 60) -> list[Node]:
        return orchestration.candidate_nodes(heartbeat_ttl_s)

    def choose_node(
        self,
        needed_vcpus: int,
        needed_mem_mb: int,
        heartbeat_ttl_s: int = 3600,
    ) -> Node | None:
        return orchestration.choose_node(needed_vcpus, needed_mem_mb, heartbeat_ttl_s)

    def _group_by_node(self, objs: Iterable) -> dict[Node, list]:
        groups: dict[Node, list] = defaultdict(list)
        for obj in objs:
            groups[obj.node].append(obj)
        return groups

    def _index_vms_by_id(self, payload: Any) -> dict[str, dict[str, Any]]:
        if isinstance(payload, dict):
            if payload and all(isinstance(k, str) for k in payload.keys()):
                return payload
            data = payload.get("data")
            if isinstance(data, list):
                return {str(vm.get("id") or vm.get("vm_id")): vm for vm in data}
            return {}
        if isinstance(payload, list):
            return {str(vm.get("id") or vm.get("vm_id")): vm for vm in payload}
        return {}

    def _batched(self, seq: list[str], size: int) -> Iterable[list[str]]:
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    def _fetch_states(
        self, service: VMServiceClient, vm_ids: list[str], batch_size: int
    ) -> dict[str, str]:
        """
        Return {vm_id: state}; if a batch fails, mark that as "error"
        """
        states: dict[str, str] = {}
        for chunk in self._batched(vm_ids, batch_size):
            try:
                resp = service.get_vms(chunk)
                index = self._index_vms_by_id(resp)
                for vm_id in chunk:
                    states[vm_id] = (index.get(vm_id) or {}).get("state", "error")
            except Exception:
                for vm_id in chunk:
                    states[vm_id] = "error"
        return states

    def _sync_statuses(self, objs: list) -> list:
        """
        Sync states and return modified objects
        """
        changed: list = []
        groups = self._group_by_node(objs)

        clients: dict[Node, VMServiceClient] = {
            creds: self._get_service_by_node(creds) for creds in groups.keys()
        }

        for creds, items in groups.items():
            vm_ids = [str(o.container_id) for o in items if o.container_id]
            if not vm_ids:
                continue

            states = self._fetch_states(clients[creds], vm_ids, self.BATCH_SIZE)

            for o in items:
                if not o.container_id:
                    continue
                new_state = states.get(str(o.container_id), "error")
                if o.status != new_state:
                    o.status = new_state
                    changed.append(o)

        return changed

    def ensure_vm_record(self, c: Container, client: VMServiceClient) -> None:
        """
        Make sure the node still has a VM record for this container before
        acting on it.

        vm-service keeps VM state in a Redis cache while Django's Container table
        is the durable source of truth. If the cache lost the record (e.g.
        vm-service restarted without persistence) an action like ``start`` would
        404. This rebuilds it from our specs first; it's idempotent (a no-op when
        the record already exists) and best-effort (any error is left for the
        caller's action to surface and for the next reconcile pass to retry).
        """
        if not c.container_id:
            return
        try:
            _ = client.ensure_vm(
                str(c.container_id),
                VMEnsure(
                    vcpus=int(c.vcpus),
                    mem_mib=int(c.memory_mb),
                    disk_gib=int(c.disk_gib),
                ),
            )
        except Exception:
            pass

    def _check_quota(self, request) -> ResourceQuota | None:
        return orchestration.check_quota(request.user)

    def _get_service_by_node(self, node: Node) -> VMServiceClient:
        return orchestration.get_service_by_node(node)

    def _get_service(self, obj: Container) -> VMServiceClient:
        return orchestration.get_service(obj)
