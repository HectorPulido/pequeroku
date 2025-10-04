import json
import time
import types

import pytest

from implementations.store import RedisStore
from models import VMRecord, VMState


# ----------------------
# Fakes for Redis client
# ----------------------
class _FakePipeline:
    def __init__(self, backing):
        self._backing = backing
        self._ops: list[tuple[str, tuple]] = []

    def set(self, key, value):
        self._ops.append(("set", (key, value)))
        return self

    def sadd(self, key, member):
        self._ops.append(("sadd", (key, member)))
        return self

    def get(self, key):  # not used in code under test via pipeline
        self._ops.append(("get", (key,)))
        return self

    def execute(self):
        out = []
        for op, args in self._ops:
            if op == "set":
                key, value = args
                self._backing._data[key] = value
                out.append(True)
            elif op == "sadd":
                key, member = args
                self._backing._sets.setdefault(key, set()).add(member)
                out.append(1)
            elif op == "get":
                key = args[0]
                out.append(self._backing._data.get(key))
        self._ops.clear()
        return out


class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    def pipeline(self):
        return _FakePipeline(self)

    def get(self, key):
        return self._data.get(key)

    def smembers(self, key):
        return set(self._sets.get(key, set()))

    # Helper to simulate from_url constructor in Redis class
    @classmethod
    def from_url(cls, url, decode_responses=True):
        return cls()


# ----------------------
# Fixtures
# ----------------------
@pytest.fixture(autouse=True)
def patch_redis_client(monkeypatch):
    # RedisStore imports Redis class directly; patch it to provide our fake .from_url
    class _DummyRedisClass:
        @classmethod
        def from_url(cls, url, decode_responses=True):
            return _FakeRedis()

    monkeypatch.setattr("implementations.store.Redis", _DummyRedisClass)
    yield


# ----------------------
# Tests
# ----------------------
def _make_vm(id_: str = "vm-1") -> VMRecord:
    return VMRecord(
        id=id_,
        state=VMState.provisioning,
        workdir=f"/tmp/{id_}",
        vcpus=2,
        mem_mib=512,
        disk_gib=10,
        ssh_port=None,
        ssh_user=None,
    )


def test_put_get_roundtrip_json_types(monkeypatch):
    store = RedisStore(url="redis://dummy/0", namespace="ns")

    # Ensure SSH alive check passes during reconciliation for this test
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "implementations.store.socket.create_connection", lambda *a, **k: _Conn()
    )

    vm = _make_vm("a1")
    store.put(vm)

    loaded = store.get("a1")
    assert loaded.id == vm.id
    assert isinstance(loaded.vcpus, int) and loaded.vcpus == 2
    assert isinstance(loaded.mem_mib, int) and loaded.mem_mib == 512
    assert isinstance(loaded.disk_gib, int) and loaded.disk_gib == 10
    assert loaded.ssh_port is None
    assert loaded.ssh_user is None
    assert loaded.state == VMState.provisioning

    # Update ssh fields and ensure they serialize as ints
    vm.ssh_port = 2222
    vm.ssh_user = "root"
    vm.state = VMState.running
    store.put(vm)

    loaded2 = store.get("a1")
    assert loaded2.state == VMState.running
    assert isinstance(loaded2.ssh_port, int) and loaded2.ssh_port == 2222
    assert loaded2.ssh_user == "root"


def test_set_status_updates_state_and_updated_at():
    store = RedisStore(url="redis://dummy/0", namespace="ns")

    vm = _make_vm("b1")
    store.put(vm)
    before = store.get("b1").updated_at

    store.set_status(vm, VMState.running, error_reason="ok")
    after = store.get("b1")

    assert after.state == VMState.running
    assert after.error_reason == "ok"
    assert after.updated_at >= before


def test_get_missing_raises_keyerror():
    store = RedisStore(url="redis://dummy/0", namespace="ns")
    with pytest.raises(KeyError):
        _ = store.get("nope")


def test_ssh_alive_true_false(monkeypatch):
    store = RedisStore(url="redis://dummy/0", namespace="ns")

    # None/0 port -> False
    assert store._ssh_alive(None) is False

    # Success path: return a dummy context manager
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "implementations.store.socket.create_connection",
        lambda addr, timeout=1.5: _Conn(),
    )
    assert store._ssh_alive(2222) is True

    # Failure path: raise
    def _raise(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(
        "implementations.store.socket.create_connection",
        _raise,
    )
    assert store._ssh_alive(2222) is False


def test_all_reconcile_marks_stopped_if_ssh_dead(monkeypatch):
    store = RedisStore(url="redis://dummy/0", namespace="ns")

    # VM running with ssh_port
    vm = _make_vm("c1")
    vm.state = VMState.running
    vm.ssh_port = 2222
    vm.ssh_user = "root"
    store.put(vm)

    # VM stopped (should remain stopped)
    vm2 = _make_vm("c2")
    vm2.state = VMState.stopped
    store.put(vm2)

    # SSH is dead -> socket.create_connection raises
    monkeypatch.setattr(
        "implementations.store.socket.create_connection",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("unreachable")),
    )

    all_map = store.all()
    assert set(all_map.keys()) == {"c1", "c2"}

    # VM c1 reconciled to stopped with error reason
    vm_c1 = all_map["c1"]
    assert vm_c1.state == VMState.stopped
    assert (
        isinstance(vm_c1.error_reason, str)
        and "reconciled: ssh port not reachable" in vm_c1.error_reason
    )

    # persisted as well
    reloaded = store.get("c1")
    assert reloaded.state == VMState.stopped
    assert "reconciled: ssh port not reachable" in (reloaded.error_reason or "")

    # VM c2 remains stopped
    assert all_map["c2"].state == VMState.stopped


def test_reconcile_all_counts_only_existing():
    store = RedisStore(url="redis://dummy/0", namespace="ns")

    # Put one VM
    vm = _make_vm("d1")
    store.put(vm)

    # Add a phantom id to ids set via pipeline
    p = store.r.pipeline()  # type: ignore[attr-defined]
    p.sadd(store.ids_key, "missing-id")
    p.execute()

    # It will iterate ids {"d1","missing-id"}; get("missing-id") should raise KeyError inside reconcile_all
    # and not count toward cnt
    cnt = store.reconcile_all()
    assert cnt == 1
