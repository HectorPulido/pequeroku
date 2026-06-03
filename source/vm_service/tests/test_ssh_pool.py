import types
import pytest

import implementations.ssh_pool as ssh_pool


class FakeTransport:
    def __init__(self, active=True):
        self.active = active

    def is_active(self):
        return self.active


class FakeSFTP:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeCLI:
    def __init__(self):
        self._t = FakeTransport(active=True)
        self.closed = False
        self.sftp = FakeSFTP()

    def get_transport(self):
        return self._t

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_pool(monkeypatch):
    # Isolate per-test: the pool keeps module-global idle lists + semaphores.
    monkeypatch.setattr(ssh_pool, "_idle", {})
    monkeypatch.setattr(ssh_pool, "_sems", {})

    made: list[FakeCLI] = []

    def fake_connect(ssh_port, ssh_user):
        c = FakeCLI()
        made.append(c)
        return c

    monkeypatch.setattr(ssh_pool, "_connect", fake_connect)
    return made


def _vm(vm_id="vm-pool"):
    return types.SimpleNamespace(id=vm_id, ssh_port=2222, ssh_user="root")


def test_borrow_yields_cli_and_sftp(reset_pool):
    vm = _vm()
    with ssh_pool.borrow(vm) as conn:
        assert isinstance(conn.cli, FakeCLI)
        assert conn.sftp is conn.cli.sftp
    assert len(reset_pool) == 1


def test_healthy_connection_is_reused(reset_pool):
    vm = _vm()
    with ssh_pool.borrow(vm) as c1:
        first = c1.cli
    with ssh_pool.borrow(vm) as c2:
        second = c2.cli
    assert first is second  # returned to the pool and reused
    assert len(reset_pool) == 1


def test_connection_dropped_on_error(reset_pool):
    vm = _vm()
    bad = None
    with pytest.raises(RuntimeError):
        with ssh_pool.borrow(vm) as conn:
            bad = conn.cli
            raise RuntimeError("boom")
    assert bad is not None and bad.closed is True  # closed, not returned to pool
    with ssh_pool.borrow(vm) as conn2:
        assert conn2.cli is not bad  # a fresh connection
    assert len(reset_pool) == 2


def test_dead_connection_is_recreated(reset_pool):
    vm = _vm()
    with ssh_pool.borrow(vm) as c1:
        conn1 = c1.cli
    conn1._t.active = False  # transport died while idle
    with ssh_pool.borrow(vm) as c2:
        assert c2.cli is not conn1
    assert conn1.closed is True
    assert len(reset_pool) == 2


def test_drop_pool_closes_idle(reset_pool):
    vm = _vm("vm-drop")
    with ssh_pool.borrow(vm) as c1:
        conn1 = c1.cli
    ssh_pool.drop_pool("vm-drop")
    assert conn1.closed is True
    assert "vm-drop" not in ssh_pool._idle
