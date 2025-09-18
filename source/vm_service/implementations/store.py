import json
import time
from typing import Dict, Optional
import socket
import redis
from qemu_manager.models import VMState, VMRecord


class RedisStore:
    def __init__(
        self,
        url: Optional[str] = None,
        namespace: str = "vmservice",
        provisioning_grace_s: int = 900,  # 15 mins default
    ) -> None:
        if not url:
            return

        self.r = redis.Redis.from_url(
            url,
            decode_responses=True,
        )
        self.ns = namespace
        self.ids_key = f"{self.ns}:vms"
        self.provisioning_grace_s = provisioning_grace_s

    # ---- Keys ----
    def _key(self, vm_id: str) -> str:
        return f"{self.ns}:vm:{vm_id}"

    # ---- (de)Deserialization ----
    def _to_dict(self, vm) -> dict:
        state = vm.state.value if hasattr(vm.state, "value") else str(vm.state)
        if state.startswith("VMState."):
            state = state.split(".", 1)[1]
        return {
            "id": vm.id,
            "state": state,
            "workdir": vm.workdir,
            "vcpus": int(vm.vcpus),
            "mem_mib": int(vm.mem_mib),
            "disk_gib": int(vm.disk_gib),
            "ssh_port": (None if vm.ssh_port is None else int(vm.ssh_port)),
            "ssh_user": vm.ssh_user,
            "key_ref": vm.key_ref,
            "error_reason": vm.error_reason,
            "created_at": float(vm.created_at),
            "updated_at": float(vm.updated_at),
        }

    def _from_dict(self, d: dict):
        state_str = d["state"]
        if state_str.startswith("VMState."):
            state_str = state_str.split(".", 1)[1]
        return VMRecord(
            id=d["id"],
            state=VMState(state_str),
            workdir=d["workdir"],
            vcpus=int(d["vcpus"]),
            mem_mib=int(d["mem_mib"]),
            disk_gib=int(d["disk_gib"]),
            ssh_port=(
                None
                if d.get("ssh_port")
                in (
                    None,
                    "",
                )
                else int(d["ssh_port"])
            ),
            ssh_user=d.get("ssh_user"),
            key_ref=d.get("key_ref"),
            error_reason=d.get("error_reason"),
            created_at=float(d["created_at"]),
            updated_at=float(d["updated_at"]),
        )

    # ---- Liveness ----
    @staticmethod
    def _ssh_alive(port: Optional[int], timeout: float = 1.5) -> bool:
        if not port:
            return False
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
                return True
        except Exception:
            return False

    def _reconcile(self, vm):
        if vm.state == VMState.running and not self._ssh_alive(vm.ssh_port):
            self.set_status(
                vm, VMState.stopped, error_reason="reconciled: ssh port not reachable"
            )
        elif vm.state == VMState.provisioning:
            age = time.time() - vm.booted_at
            if age > self.provisioning_grace_s and not self._ssh_alive(vm.ssh_port):
                self.set_status(
                    vm, VMState.stopped, error_reason="provisioning-timeout"
                )
        return vm

    # ---- API compatible ----
    def put(self, vm) -> None:
        vm.updated_at = time.time()
        data = self._to_dict(vm)
        key = self._key(vm.id)
        p = self.r.pipeline()
        p.set(key, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        p.sadd(self.ids_key, vm.id)
        p.execute()

    def get(self, vm_id: str):
        s = self.r.get(self._key(vm_id))
        if s is None:
            raise KeyError(vm_id)
        # pyrefly: ignore  # bad-argument-type
        vm = self._from_dict(json.loads(s))
        return self._reconcile(vm)

    def all(self) -> Dict[str, "VMRecord"]:
        ids = self.r.smembers(self.ids_key)
        if not ids:
            return {}
        p = self.r.pipeline()
        # pyrefly: ignore  # no-matching-overload
        ordered = sorted(ids)
        for i in ordered:
            p.get(self._key(i))
        vals = p.execute()
        out: Dict[str, "VMRecord"] = {}
        for i, s in zip(ordered, vals):
            if not s:
                continue
            try:
                vm = self._from_dict(json.loads(s))
                out[i] = self._reconcile(vm)
            except Exception:
                continue
        return out

    def reconcile_all(self) -> int:
        """Call this when service start to autohealth the catalog..."""
        cnt = 0
        # pyrefly: ignore  # no-matching-overload
        for vid in list(self.r.smembers(self.ids_key)):
            try:
                _ = self.get(vid)
                cnt += 1
            except KeyError:
                continue
        return cnt

    def set_status(
        self,
        vm,
        status: VMState,
        error_reason: Optional[str] = None,
    ):
        print(f"Setting {vm} to status: {status}, with error_reason={error_reason}")
        vm.state = status
        vm.error_reason = error_reason
        self.put(vm)
