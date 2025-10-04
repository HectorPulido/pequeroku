import os
import time

import pytest

import settings
import models
from implementations.runner import Runner
from implementations import RedisStore as _RedisStore


class InMemoryStore(_RedisStore):
    def __init__(self):
        self._data: dict[str, models.VMRecord] = {}

    def put(self, vm: models.VMRecord) -> None:
        vm.updated_at = time.time()
        self._data[vm.id] = vm

    def get(self, vm_id: str) -> models.VMRecord:
        if vm_id not in self._data:
            raise KeyError(vm_id)
        return self._data[vm_id]

    def set_status(
        self,
        vm: models.VMRecord,
        status: models.VMState,
        error_reason: str | None = None,
    ):
        vm.state = status
        vm.error_reason = error_reason
        self.put(vm)


def wait_until(predicate, timeout=2.0, interval=0.01):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def base_env(tmp_path, monkeypatch):
    base_dir = tmp_path / "vm_data"
    os.makedirs(base_dir, exist_ok=True)
    monkeypatch.setattr(settings, "VM_BASE_DIR", str(base_dir), raising=False)
    monkeypatch.setattr(settings, "VM_SSH_USER", "testuser", raising=False)
    return str(base_dir)


@pytest.fixture
def store_and_runner(base_env):
    store = InMemoryStore()
    runner = Runner(store, node_name="test-node")
    return store, runner


def _make_vm(runner: Runner, vm_id: str = "vm-1") -> models.VMRecord:
    wd = runner.workdir(vm_id)
    return models.VMRecord(
        id=vm_id,
        state=models.VMState.provisioning,
        workdir=wd,
        vcpus=2,
        mem_mib=512,
        disk_gib=10,
    )


def test_workdir_creates_directory(store_and_runner, base_env):
    store, runner = store_and_runner
    vm_id = "workdir-test"
    wd = runner.workdir(vm_id)
    assert wd.startswith(base_env)
    assert os.path.isdir(wd)


def test_start_success_sets_running_and_ports(monkeypatch, store_and_runner):
    store, runner = store_and_runner

    def fake_start_vm(workdir, vcpus, mem_mib, disk_gib, vm_id):
        return models.VMProc(
            workdir=workdir,
            overlay=os.path.join(workdir, "disk.qcow2"),
            seed_iso=os.path.join(workdir, "seed.iso"),
            port_ssh=2222,
            console_log=os.path.join(workdir, "console.log"),
            pidfile=os.path.join(workdir, "qemu.pid"),
        )

    # speed up and avoid real waiting
    monkeypatch.setattr("implementations.runner.start_vm", fake_start_vm)
    monkeypatch.setattr("implementations.runner.wait_ssh", lambda **kwargs: True)

    vm = _make_vm(runner, "vm-start-ok")
    store.put(vm)
    t0 = time.time()
    runner.start(vm)

    assert wait_until(lambda: vm.state == models.VMState.running, timeout=2.0)
    assert vm.ssh_port == 2222
    assert vm.ssh_user == "testuser"
    assert vm.proc is not None and vm.proc.port_ssh == 2222
    assert vm.booted_at >= t0


def test_start_failure_sets_error(monkeypatch, store_and_runner):
    store, runner = store_and_runner

    def fake_start_vm_fail(workdir, vcpus, mem_mib, disk_gib, vm_id):
        raise RuntimeError("boom-start")

    monkeypatch.setattr("implementations.runner.start_vm", fake_start_vm_fail)
    # even if wait_ssh is called (it won't be), keep it harmless
    monkeypatch.setattr("implementations.runner.wait_ssh", lambda **kwargs: True)

    vm = _make_vm(runner, "vm-start-fail")
    store.put(vm)
    runner.start(vm)

    assert wait_until(lambda: vm.state == models.VMState.error, timeout=2.0)
    assert "boom-start" in (vm.error_reason or "")


def test_stop_with_pidfile_kills_and_removes_pidfile(
    monkeypatch, store_and_runner, base_env
):
    store, runner = store_and_runner
    vm = _make_vm(runner, "vm-stop-pid")
    store.put(vm)

    # Prepare VM as running with proc and pidfile
    pidfile_path = os.path.join(base_env, "vms", vm.id, "qemu.pid")
    os.makedirs(os.path.dirname(pidfile_path), exist_ok=True)
    with open(pidfile_path, "w", encoding="utf-8") as f:
        f.write("12345")

    vm.proc = models.VMProc(
        workdir=vm.workdir,
        overlay=os.path.join(vm.workdir, "disk.qcow2"),
        seed_iso=os.path.join(vm.workdir, "seed.iso"),
        port_ssh=2222,
        console_log=os.path.join(vm.workdir, "console.log"),
        pidfile=pidfile_path,
    )
    vm.state = models.VMState.running

    calls = []

    def fake_killpg(pid, sig):
        calls.append((pid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)

    # Provide a channel to test _send_stop path
    class FakeChan:
        def __init__(self):
            self.closed = False
            self.sent = []

        def send(self, data):
            self.sent.append(data)

    chan = FakeChan()
    setattr(vm.proc, "chan", chan)

    runner.stop(vm, cleanup_disks=False)

    assert wait_until(lambda: vm.state == models.VMState.stopped, timeout=2.0)
    # Should have tried to kill the pid via os.killpg at least once
    assert any(pid == 12345 for pid, _ in calls)
    # pidfile should be removed
    assert not os.path.exists(pidfile_path)
    # _send_stop must have sent shutdown command
    assert any(
        "shutdown now" in (s if isinstance(s, str) else s.decode("utf-8", "ignore"))
        for s in chan.sent
    )


def test_stop_without_pidfile_uses_popen(monkeypatch, store_and_runner, base_env):
    store, runner = store_and_runner
    vm = _make_vm(runner, "vm-stop-popen")
    store.put(vm)

    class FakePopen:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.wait_called = 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.wait_called += 1
            return 0

        def kill(self):
            self.killed = True

    fp = FakePopen()
    vm.proc = models.VMProc(
        workdir=vm.workdir,
        overlay=os.path.join(vm.workdir, "disk.qcow2"),
        seed_iso=os.path.join(vm.workdir, "seed.iso"),
        port_ssh=2222,
        proc=fp,
        console_log=os.path.join(vm.workdir, "console.log"),
        pidfile=os.path.join(vm.workdir, "qemu.pid"),
    )
    vm.state = models.VMState.running

    # Ensure pidfile path that _try_to_get_pid will check does not exist (no pid)
    pidfile_check = os.path.join(base_env, "vms", vm.id, "qemu.pid")
    if os.path.exists(pidfile_check):
        os.remove(pidfile_check)

    runner.stop(vm, cleanup_disks=False)

    assert wait_until(lambda: vm.state == models.VMState.stopped, timeout=2.0)
    assert fp.terminated is True
    # kill shouldn't be necessary if wait returns promptly
    assert fp.killed is False


def test_stop_with_cleanup_removes_vm_files(monkeypatch, store_and_runner, base_env):
    store, runner = store_and_runner
    vm = _make_vm(runner, "vm-cleanup")
    store.put(vm)

    # Create files that _clean_up will remove
    target_files = [
        os.path.join(vm.workdir, "disk.qcow2"),
        os.path.join(vm.workdir, "seed.iso"),
        os.path.join(vm.workdir, "console.log"),
        os.path.join(vm.workdir, "qemu.pid"),
        os.path.join(vm.workdir, "user-data"),
        os.path.join(vm.workdir, "meta-data"),
        os.path.join(vm.workdir, "seed.iso.spec"),
    ]
    for p in target_files:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")

    vm.proc = models.VMProc(
        workdir=vm.workdir,
        overlay=target_files[0],
        seed_iso=target_files[1],
        port_ssh=2222,
        console_log=target_files[2],
        pidfile=target_files[3],
    )
    vm.state = models.VMState.running

    # No pid available; ensure _kill_by_popen branch won't raise
    class FakePopen:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    vm.proc.proc = FakePopen()

    # Ensure the pidfile path used by _try_to_get_pid does not exist (force popen path)
    pidfile_check = os.path.join(base_env, "vms", vm.id, "qemu.pid")
    if os.path.exists(pidfile_check):
        os.remove(pidfile_check)

    runner.stop(vm, cleanup_disks=True)

    assert wait_until(lambda: vm.state == models.VMState.stopped, timeout=2.0)
    # All target files should be gone
    for p in target_files:
        assert not os.path.exists(p)
