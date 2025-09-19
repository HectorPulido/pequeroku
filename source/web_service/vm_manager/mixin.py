from collections import defaultdict
from typing import Dict, Iterable, List, Any, Optional

from datetime import timedelta
from django.utils import timezone

from .models import Container, Node
from .vm_client import VMServiceClient


class VMSyncMixin:
    BATCH_SIZE = 100

    # Scheduler helpers
    def _candidate_nodes(self, heartbeat_ttl_s: int = 60) -> List[Node]:
        """
        Return active nodes with a recent heartbeat.
        """
        cutoff = timezone.now() - timedelta(seconds=heartbeat_ttl_s)
        return list(
            Node.objects.filter(active=True, healthy=True, heartbeat_at__gte=cutoff)
        )

    def choose_node(
        self,
        needed_vcpus: int,
        needed_mem_mb: int,
        heartbeat_ttl_s: int = 60,
    ) -> Optional[Node]:
        """
        Choose the best node by capacity and recent heartbeat. Returns None if no feasible node.
        """
        candidates = self._candidate_nodes(heartbeat_ttl_s)
        best: Optional[Node] = None
        best_score = float("-inf")
        for n in candidates:
            free_v, free_m = n.get_free_resources()
            if free_v < int(needed_vcpus) or free_m < int(needed_mem_mb):
                continue
            score = n.get_node_score()
            if score > best_score:
                best = n
                best_score = score
        return best

    def _group_by_node(self, objs: Iterable) -> Dict[Node, List]:
        groups: Dict[Node, List] = defaultdict(list)
        for obj in objs:
            groups[obj.node].append(obj)
        return groups

    def _index_vms_by_id(self, payload: Any) -> Dict[str, Dict[str, Any]]:
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

    def _batched(self, seq: List[str], size: int) -> Iterable[List[str]]:
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    def _fetch_states(
        self, service: VMServiceClient, vm_ids: List[str], batch_size: int
    ) -> Dict[str, str]:
        """
        Return {vm_id: state}; if a batch fails, mark that as "error"
        """
        states: Dict[str, str] = {}
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

    def _sync_statuses(self, objs: List) -> List:
        """
        Sync states and return modified objects
        """
        changed: List = []
        groups = self._group_by_node(objs)

        clients: Dict[Node, VMServiceClient] = {
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

    def _get_service_by_node(self, node: Node) -> VMServiceClient:
        return VMServiceClient(node, blocking=True)

    def _get_service(self, obj: Container) -> VMServiceClient:
        return VMServiceClient(obj.node, blocking=True)
