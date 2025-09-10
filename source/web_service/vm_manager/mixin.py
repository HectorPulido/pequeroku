from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Any, Tuple, Optional

from .models import Container, Node
from .vm_client import VMServiceClient


@dataclass(frozen=True)
class _Creds:
    host: str
    token: str


class VMSyncMixin:
    BATCH_SIZE = 100

    def _group_by_node(self, objs: Iterable) -> Dict[_Creds, List]:
        groups: Dict[_Creds, List] = defaultdict(list)
        for obj in objs:
            node = obj.node
            groups[_Creds(str(node.node_host), str(node.auth_token))].append(obj)
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

        clients: Dict[_Creds, VMServiceClient] = {
            creds: self._service(creds) for creds in groups.keys()
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

    def _service(self, creds: _Creds) -> VMServiceClient:
        return VMServiceClient(base_url=creds.host, token=creds.token)

    def _get_service(self, obj: Container) -> VMServiceClient:
        node: Node = obj.node
        return VMServiceClient(
            base_url=str(node.node_host),
            token=str(node.auth_token),
        )
