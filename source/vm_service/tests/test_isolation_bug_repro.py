"""Reproduction of the container ISOLATION bug.

Symptom (seen in prod): two distinct ``Container`` records — two different
``container_id`` UUIDs (e.g. ``773111b2…`` and ``458db977…``) — open the terminal
and the file tree of the SAME physical VM. A file created from one container
appears in the other; writes cross over.

Root cause proven here: the vm-service routes EVERY operation to
``127.0.0.1:<ssh_port>`` (see ``ssh_cache._connect`` / ``ssh_pool.borrow``). That
port is the ONLY thing that identifies the physical machine, and it is fragile:

1. ``pick_free_port()`` binds ``:0``, reads the number and CLOSES the socket, so
   the port is not reserved until QEMU finally binds it — two concurrent
   ``start_vm`` calls can hand out the SAME port (TOCTOU).
2. ``Runner.stop`` never clears ``ssh_port``: a stopped VM keeps a stale port in
   Redis, which the next boot can reuse.
3. ``store._reconcile`` marks a VM "running" when *anything* answers on its port —
   it never checks that the machine behind the port is the intended VM.

When two ``VMRecord``s end up with the same ``ssh_port``, both resolve to the one
live QEMU behind it. These tests reproduce each broken link, plus the end-to-end
break, WITHOUT booting real QEMU: the only thing faked is the transport at the
exact boundary the code trusts — ``connect to 127.0.0.1:<port>``. Physical
machines are modeled as a registry keyed BY PORT, so the real routing code
(``store`` + ``_reconcile`` + ``ssh_pool.borrow`` + the ``/execute-sh`` route)
decides which machine each container reaches.
"""

from __future__ import annotations

import shlex
import socket

import pytest
from fastapi.testclient import TestClient

import main
import settings
from implementations import ssh_pool
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
        return _FakeTransport()

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


def _fake_create_connection(addr, timeout=1.5):
    """A port is 'alive' iff a machine is bound to it (identity-blind, like prod)."""
    _host, port = addr
    if int(port) in MACHINES:
        return _AliveCM()
    raise OSError("unreachable")


def _install(monkeypatch) -> RedisStore:
    monkeypatch.setattr(ssh_pool, "_connect", _fake_connect, raising=True)
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
    MACHINES[5001] = FakeMachine("vm-A")
    MACHINES[5002] = FakeMachine("vm-B")

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
    assert h.json()["stdout"].strip() == "vm-B"


# ---------------------------------------------------------------------------
# THE BUG (residual, tolerant path): if a collision somehow exists on UNMARKED
# (legacy) VMs, routing is still by port. The fixes PREVENT the collision from
# forming (reserved ports + clear-on-stop); the identity marker (next test) BLOCKS
# operating on it once VMs are stamped. This documents the tolerant fallback.
# ---------------------------------------------------------------------------
def test_unmarked_vms_still_route_by_port_tolerant(monkeypatch):
    store = _install(monkeypatch)

    # ONE surviving QEMU on port 5001, booted from container 232's disk (a
    # duplicate copies the disk verbatim, so it carries 232's baked hostname).
    # No identity marker set -> assert_vm_identity is tolerant and allows it.
    survivor = FakeMachine("773111b2-39c2-418c-b90e-2ee5f4b61890")
    MACHINES[5001] = survivor

    # Container 232 (hectorpulido.net) — legitimately on 5001.
    c232 = _vm("773111b2-39c2-418c-b90e-2ee5f4b61890", 5001)
    # Container 257 (heyform) — a DIFFERENT container_id, but the port picker
    # handed it 5001 too; its own QEMU lost the bind and died.
    c257 = _vm("458db977-dc99-4925-a324-c93f9025ef00", 5001)
    store.put(c232)
    store.put(c257)

    client = TestClient(main.app)

    # Both are reported RUNNING though only one machine exists.
    assert store.get(c232.id).state == VMState.running
    assert store.get(c257.id).state == VMState.running

    # Create a file FROM container 232.
    w = client.post(
        f"/vms/{c232.id}/execute-sh",
        json={
            "command": "printf %s 'Archivo creado desde 232' > /app/heyform/test.txt"
        },
        headers=AUTH,
    )
    assert w.status_code == 200 and w.json()["ok"]

    # Read it FROM container 257 — it is there. Same machine. Isolation broken.
    r = client.post(
        f"/vms/{c257.id}/execute-sh",
        json={"command": "cat /app/heyform/test.txt"},
        headers=AUTH,
    )
    assert r.json()["ok"]
    assert r.json()["stdout"] == "Archivo creado desde 232"

    # And 257's terminal reports 232's hostname, exactly like the screenshots.
    h = client.post(
        f"/vms/{c257.id}/execute-sh", json={"command": "hostname"}, headers=AUTH
    )
    assert h.json()["stdout"].strip() == "773111b2-39c2-418c-b90e-2ee5f4b61890"


# ---------------------------------------------------------------------------
# THE FIX, end to end: with the identity marker stamped, container 257 can NO
# LONGER reach container 232's machine even if their ports collide.
# ---------------------------------------------------------------------------
def test_identity_marker_blocks_cross_wiring(monkeypatch):
    store = _install(monkeypatch)

    # The one live QEMU on port 5001 is container 232, and it is STAMPED with 232's
    # id (write_vm_id_marker does this on every boot).
    survivor = FakeMachine("773111b2-39c2-418c-b90e-2ee5f4b61890")
    survivor.fs["/etc/pequeroku-vm-id"] = "773111b2-39c2-418c-b90e-2ee5f4b61890"
    MACHINES[5001] = survivor

    c232 = _vm("773111b2-39c2-418c-b90e-2ee5f4b61890", 5001)
    c257 = _vm("458db977-dc99-4925-a324-c93f9025ef00", 5001)  # collided onto 5001
    store.put(c232)
    store.put(c257)

    client = TestClient(main.app)

    # 232 reaches its own machine fine (marker matches).
    r232 = client.post(
        f"/vms/{c232.id}/execute-sh", json={"command": "hostname"}, headers=AUTH
    )
    assert r232.json()["ok"]
    assert r232.json()["stdout"].strip() == "773111b2-39c2-418c-b90e-2ee5f4b61890"

    # 257 tries to operate on port 5001 -> marker says 773111b2 != 458db977 ->
    # assert_vm_identity raises -> the endpoint refuses. No cross-wiring.
    r257 = client.post(
        f"/vms/{c257.id}/execute-sh",
        json={"command": "cat /app/heyform/test.txt"},
        headers=AUTH,
    )
    assert r257.json()["ok"] is False  # blocked, did not read 232's machine
