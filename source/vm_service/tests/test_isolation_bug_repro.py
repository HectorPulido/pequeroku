"""Regression tests for SSH port reuse and cross-VM routing."""

from __future__ import annotations

import shlex
import socket

import pytest
from fastapi.testclient import TestClient

import main
import settings
from implementations import ssh_cache, ssh_pool
from implementations import runner as runner_mod
from implementations.store import RedisStore
from qemu_manager.ports import pick_free_port
from routes import vms as vms_routes
from models import VMRecord, VMState


# ---------------------------------------------------------------------------
# Model of "physical machines", keyed by the loopback port QEMU forwarded to.
# This mirrors reality: SSHing to 127.0.0.1:<port> reaches whatever VM is bound
# to that port — nothing more, nothing less.
# ---------------------------------------------------------------------------
class FakeMachine:
    def __init__(self, hostname: str) -> None:
        self.hostname = hostname
        self.fs: dict[str, str] = {}


MACHINES: dict[int, FakeMachine] = {}


class _FakeChannel:
    def settimeout(self, _t):  # noqa: D401
        return None

    def recv_exit_status(self) -> int:
        return 0

    def close(self):
        return None


class _FakeStdout:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.channel = _FakeChannel()

    def read(self) -> bytes:
        return self._data


class _FakeTransport:
    sock = None

    def is_active(self) -> bool:
        return True

    def set_keepalive(self, _n):
        return None


class FakeExecClient:
    """An SSH connection to whatever machine is bound to the target port.

    Understands the tiny command set the tests drive: ``hostname``, ``cat PATH``
    and ``printf %s 'TEXT' > PATH``. That is enough to prove "write here, read
    there → same machine".
    """

    def __init__(self, machine: FakeMachine) -> None:
        self.machine = machine

    def exec_command(self, command: str):
        out = self._run(command).encode()
        return None, _FakeStdout(out), _FakeStdout(b"")

    def _run(self, command: str) -> str:
        c = command.strip()
        m = self.machine
        if c == "hostname":
            return m.hostname + "\n"
        if c.startswith("cat "):
            path = shlex.split(c)[1]
            return m.fs.get(path, "")
        if c.startswith("printf ") and ">" in c:
            left, path = c.rsplit(">", 1)
            tokens = shlex.split(left)  # ['printf', '%s', 'TEXT']
            text = tokens[2] if len(tokens) >= 3 else ""
            m.fs[path.strip()] = text
            return ""
        return ""

    def open_sftp(self):
        return object()  # borrow() stores it but the exec path never uses it

    def get_transport(self):
        transport = _FakeTransport()
        transport.sock = self.machine
        return transport

    def close(self):
        return None


class _AliveCM:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _DummyRedisClass:
    @classmethod
    def from_url(cls, url, decode_responses=True):
        return _FakeRedis()


class _FakePipeline:
    def __init__(self, backing: "_FakeRedis") -> None:
        self._backing = backing
        self._ops: list[tuple[str, tuple]] = []

    def set(self, key, value):
        self._ops.append(("set", (key, value)))
        return self

    def sadd(self, key, member):
        self._ops.append(("sadd", (key, member)))
        return self

    def execute(self):
        out = []
        for op, args in self._ops:
            if op == "set":
                self._backing._data[args[0]] = args[1]
                out.append(True)
            elif op == "sadd":
                self._backing._sets.setdefault(args[0], set()).add(args[1])
                out.append(1)
        self._ops.clear()
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    def pipeline(self):
        return _FakePipeline(self)

    def get(self, key):
        return self._data.get(key)

    def smembers(self, key):
        return set(self._sets.get(key, set()))


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def _fake_connect(ssh_port, ssh_user):
    """Reach whatever machine is bound to that loopback port (or refuse)."""
    machine = MACHINES.get(int(ssh_port))
    if machine is None:
        raise OSError(f"connection refused: nothing on 127.0.0.1:{ssh_port}")
    return FakeExecClient(machine)


def _verify_fake_peer(peer, pidfile):
    if pidfile != f"/tmp/{peer.hostname}/qemu.pid":
        raise ssh_cache.VMIdentityMismatch("Cannot verify SSH peer for VM")


def _fake_create_connection(addr, timeout=1.5):
    """A port is 'alive' iff a machine is bound to it (identity-blind, like prod)."""
    _host, port = addr
    if int(port) in MACHINES:
        return _AliveCM()
    raise OSError("unreachable")


def _install(monkeypatch) -> RedisStore:
    monkeypatch.setattr(ssh_pool, "_connect", _fake_connect, raising=True)
    monkeypatch.setattr(ssh_cache, "verify_ssh_peer", _verify_fake_peer)
    monkeypatch.setattr(
        "implementations.store.socket.create_connection", _fake_create_connection
    )
    monkeypatch.setattr("implementations.store.Redis", _DummyRedisClass)
    # Real store + real _reconcile, backed by the fake redis.
    store = RedisStore(url="redis://dummy/0", namespace="vmservice")
    monkeypatch.setattr(vms_routes, "store", store, raising=False)
    monkeypatch.setattr(main, "store", store, raising=False)
    return store


def _vm(id_: str, port: int) -> VMRecord:
    return VMRecord(
        id=id_,
        state=VMState.running,
        workdir=f"/tmp/{id_}",
        vcpus=2,
        mem_mib=512,
        disk_gib=10,
        ssh_port=port,
        ssh_user="root",
    )


@pytest.fixture(autouse=True)
def _reset_globals():
    MACHINES.clear()
    ssh_pool._idle.clear()
    ssh_pool._sems.clear()
    yield
    MACHINES.clear()
    ssh_pool._idle.clear()
    ssh_pool._sems.clear()


AUTH = {"Authorization": "Bearer testtoken"}


# ---------------------------------------------------------------------------
# FIX for link #1: pick_free_port now reserves the port so two concurrent
# start_vm calls can never be handed the same number.
# ---------------------------------------------------------------------------
def test_pick_free_port_skips_reserved(monkeypatch):
    """A port already handed out (reserved) is never returned again until released."""
    from qemu_manager import ports

    # Force the OS probe to propose 5000 twice, then 5001 — so the reservation is
    # the only thing that can make the two picks differ.
    seq = iter([5000, 5000, 5001])

    class _FakeSock:
        def bind(self, _addr):
            self._p = next(seq)

        def getsockname(self):
            return ("127.0.0.1", self._p)

        def close(self):
            return None

    monkeypatch.setattr(ports.socket, "socket", lambda *a, **k: _FakeSock())
    ports._reserved.clear()
    try:
        a = ports.pick_free_port()  # proposes 5000 -> reserved
        b = ports.pick_free_port()  # proposes 5000 (reserved) -> retries -> 5001
        assert a == 5000 and b == 5001
        # Once released, the number is available again.
        ports.release_port(a)
        c = iter([5000])
        monkeypatch.setattr(
            ports.socket,
            "socket",
            lambda *aa, **kk: type(
                "S",
                (),
                {
                    "bind": lambda self, _x: None,
                    "getsockname": lambda self: ("127.0.0.1", next(c)),
                    "close": lambda self: None,
                },
            )(),
        )
        assert ports.pick_free_port() == 5000
    finally:
        ports._reserved.clear()


# ---------------------------------------------------------------------------
# FIX for link #2: stop() now clears ssh_port so a stopped record can't alias.
# ---------------------------------------------------------------------------
def test_stop_clears_ssh_port(monkeypatch, tmp_path):
    class _SyncThread:
        def __init__(self, target=None, daemon=None, **_kw):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    class _Store:
        def set_status(self, vm, status, error_reason=None):
            vm.state = status
            vm.error_reason = error_reason

        def put(self, vm):
            return None

    monkeypatch.setattr(runner_mod.threading, "Thread", _SyncThread)
    monkeypatch.setattr(settings, "VM_BASE_DIR", str(tmp_path), raising=False)

    r = runner_mod.Runner(_Store(), "test-node")
    vm = _vm("vm-stale", 5555)

    r.stop(vm)

    assert vm.state == VMState.stopped
    # The stale port is gone — the stopped record can no longer point at whatever VM
    # later binds 5555.
    assert vm.ssh_port is None


def test_reboot_keeps_ssh_port(monkeypatch, tmp_path):
    """reboot passes clear_port=False so the restart's fresh port isn't clobbered."""

    class _SyncThread:
        def __init__(self, target=None, daemon=None, **_kw):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    class _Store:
        def set_status(self, vm, status, error_reason=None):
            vm.state = status

        def put(self, vm):
            return None

    monkeypatch.setattr(runner_mod.threading, "Thread", _SyncThread)
    monkeypatch.setattr(settings, "VM_BASE_DIR", str(tmp_path), raising=False)

    r = runner_mod.Runner(_Store(), "test-node")
    vm = _vm("vm-reboot", 5555)

    r.stop(vm, clear_port=False)

    assert vm.ssh_port == 5555


# ---------------------------------------------------------------------------
# Root-cause link #3: reconcile can't tell it's the WRONG machine.
# ---------------------------------------------------------------------------
def test_reconcile_reports_running_even_when_port_belongs_to_another_vm(monkeypatch):
    store = _install(monkeypatch)
    # Only machine A is alive, on port 5001.
    MACHINES[5001] = FakeMachine("vm-A")

    # B's own QEMU is gone, but its record was left pointing at 5001 (A's port).
    b = _vm("vm-B", 5001)
    store.put(b)

    got = store.get("vm-B")
    # "Something answers on 5001" -> reported running, though that is A's VM.
    assert got.state == VMState.running


# ---------------------------------------------------------------------------
# Sanity: with DISTINCT ports the harness keeps VMs isolated (so the failure
# below is the shared port, not the test setup).
# ---------------------------------------------------------------------------
def test_baseline_isolation_holds_with_distinct_ports(monkeypatch):
    store = _install(monkeypatch)
    MACHINES[5001] = FakeMachine("id-A")
    MACHINES[5002] = FakeMachine("id-B")

    a = _vm("id-A", 5001)
    b = _vm("id-B", 5002)
    store.put(a)
    store.put(b)

    client = TestClient(main.app)

    w = client.post(
        f"/vms/{a.id}/execute-sh",
        json={"command": "printf %s 'secret-of-A' > /app/note.txt"},
        headers=AUTH,
    )
    assert w.status_code == 200 and w.json()["ok"]

    r = client.post(
        f"/vms/{b.id}/execute-sh",
        json={"command": "cat /app/note.txt"},
        headers=AUTH,
    )
    assert r.json()["ok"]
    assert r.json()["stdout"] == ""  # B cannot see A's file — properly isolated

    h = client.post(
        f"/vms/{b.id}/execute-sh", json={"command": "hostname"}, headers=AUTH
    )
    assert h.json()["stdout"].strip() == "id-B"


def test_peer_check_blocks_cross_wiring_on_shared_port(monkeypatch):
    store = _install(monkeypatch)
    owner = _vm("vm-owner", 5001)
    other = _vm("vm-other", 5001)
    store.put(owner)
    store.put(other)
    MACHINES[5001] = FakeMachine(owner.id)
    client = TestClient(main.app)

    authorized = client.post(
        f"/vms/{owner.id}/execute-sh", json={"command": "hostname"}, headers=AUTH
    )
    assert authorized.json()["ok"]
    assert authorized.json()["stdout"].strip() == owner.id

    denied = client.post(
        f"/vms/{other.id}/execute-sh", json={"command": "hostname"}, headers=AUTH
    )
    assert denied.json()["ok"] is False
    assert not denied.json().get("stdout")
