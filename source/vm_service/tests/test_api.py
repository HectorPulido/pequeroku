import os
import sys
import time
import types
import pathlib

import pytest
from fastapi.testclient import TestClient

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_PKG_ROOT = _THIS_DIR.parent  # vm_service/
sys.path.insert(0, str(_PKG_ROOT))

import settings  # noqa: E402
import models  # noqa: E402
from routes import vms  # noqa: E402
import main  # noqa: E402


# ----------------------
# Test Utilities / Fakes
# ----------------------
class InMemoryStore:
    def __init__(self):
        self._data: dict[str, models.VMRecord] = {}

    def put(self, vm: models.VMRecord) -> None:
        vm.updated_at = time.time()
        self._data[vm.id] = vm

    def get(self, vm_id: str) -> models.VMRecord:
        if vm_id not in self._data:
            raise KeyError(vm_id)
        return self._data[vm_id]

    def all(self) -> dict[str, models.VMRecord]:
        return dict(self._data)

    def set_status(
        self,
        vm: models.VMRecord,
        status: models.VMState,
        error_reason: str | None = None,
    ):
        vm.state = status
        vm.error_reason = error_reason
        self.put(vm)


class FakeRunner:
    def __init__(self, store: InMemoryStore, node_name: str, base_dir: str):
        self.store = store
        self.node_name = node_name
        self._base_dir = base_dir

    def workdir(self, vm_id: str) -> str:
        wd = os.path.join(self._base_dir, "vms", vm_id)
        os.makedirs(wd, exist_ok=True)
        return wd

    def start(self, vm: models.VMRecord) -> None:
        vm.ssh_port = 2222
        vm.ssh_user = "root"
        # minimal proc structure for endpoints like tail_console
        vm.proc = models.VMProc(
            workdir=vm.workdir,
            overlay=os.path.join(vm.workdir, "disk.qcow2"),
            seed_iso=os.path.join(vm.workdir, "seed.iso"),
            port_ssh=vm.ssh_port,
            proc=None,
            console_log=os.path.join(vm.workdir, "console.log"),
            pidfile=os.path.join(vm.workdir, "qemu.pid"),
        )
        self.store.set_status(vm, models.VMState.running)

    def stop(self, vm: models.VMRecord, cleanup_disks: bool = False) -> None:
        self.store.set_status(vm, models.VMState.stopped)


class FakeTimer:
    def __init__(self, interval: float, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def start(self):
        # Run immediately for deterministic tests
        self.func(*self.args, **self.kwargs)


class FakeChannel:
    def __init__(self):
        self._timeout = None

    def settimeout(self, t):
        self._timeout = t


class FakeFile:
    def __init__(self, data: bytes):
        self._data = data
        self.channel = FakeChannel()

    def read(self) -> bytes:
        return self._data


class FakeSSHClient:
    def __init__(self, stdout_data: bytes = b"", stderr_data: bytes = b""):
        self._stdout = stdout_data
        self._stderr = stderr_data

    def exec_command(self, command: str):
        return None, FakeFile(self._stdout), FakeFile(self._stderr)

    # For TTY usage we won't use invoke_shell here (mocked elsewhere),
    # but define it for safety.
    def invoke_shell(self, width=120, height=32):
        return types.SimpleNamespace(
            closed=False,
            recv=lambda n: b"",
            send=lambda data: None,
            settimeout=lambda t: None,
            close=lambda: None,
        )


class FakeTTYBridge:
    def __init__(self, ws, vm):
        self.ws = ws
        self.vm = vm
        self.started = False
        self.closed = False

    def start(self):
        # Do nothing; we won't spawn any background thread
        self.started = True

    async def send(self, text: str):
        # Echo back to the websocket
        await self.ws.send_text(f"REMOTE:{text}")

    def close(self):
        self.closed = True


# ----------------------
# Pytest Fixtures
# ----------------------
@pytest.fixture(autouse=True)
def patch_auth_token(monkeypatch):
    # Force a known token for tests
    monkeypatch.setattr(settings, "AUTH_TOKEN", "testtoken", raising=False)


@pytest.fixture
def auth_header():
    return {"Authorization": "Bearer testtoken"}


@pytest.fixture
def store_and_runner(tmp_path, monkeypatch):
    # Replace the global stores/runners in modules
    base_dir = tmp_path / "vm_data"
    os.makedirs(base_dir, exist_ok=True)

    test_store = InMemoryStore()
    test_runner = FakeRunner(test_store, "test-node", str(base_dir))

    # Patch settings VM_BASE_DIR so endpoints that read files work under tmpdir
    monkeypatch.setattr(settings, "VM_BASE_DIR", str(base_dir), raising=False)

    # Patch in modules
    monkeypatch.setattr(vms, "store", test_store, raising=False)
    monkeypatch.setattr(vms, "runner", test_runner, raising=False)
    monkeypatch.setattr(main, "store", test_store, raising=False)
    monkeypatch.setattr(main, "runner", test_runner, raising=False)

    # Patch Timer in vms for deterministic reboot
    import threading

    monkeypatch.setattr(threading, "Timer", FakeTimer, raising=True)

    return test_store, test_runner, str(base_dir)


@pytest.fixture
def client(store_and_runner, monkeypatch):
    # Patch TTYBridge so WS endpoint is deterministic
    monkeypatch.setattr(main, "TTYBridge", FakeTTYBridge, raising=False)
    return TestClient(main.app)


# ----------------------
# Tests
# ----------------------
def test_health_ok(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": "True"}


def test_auth_required_for_vms_endpoints(client: TestClient):
    # Missing token
    r = client.get("/vms/")
    assert r.status_code == 401

    # Wrong token
    r = client.get("/vms/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


def test_create_get_list_delete_vm_flow(
    client: TestClient, auth_header, store_and_runner
):
    # Create VM
    payload = {"vcpus": 2, "mem_mib": 512, "disk_gib": 10}
    r = client.post("/vms/", headers=auth_header, json=payload)
    assert r.status_code == 201
    created = r.json()
    assert "id" in created
    vm_id = created["id"]
    assert created["node"] == "test-node"
    assert created["ssh_host"] == "127.0.0.1"
    assert created["state"] in {"provisioning", "running", "stopped", "error"}

    # Get VM
    r = client.get(f"/vms/{vm_id}", headers=auth_header)
    assert r.status_code == 200
    got = r.json()
    assert got["id"] == vm_id

    # List VMs by ids
    r = client.get(f"/vms/list/{vm_id}", headers=auth_header)
    assert r.status_code == 200
    lst = r.json()
    assert any(x["id"] == vm_id for x in lst)

    # List VMs
    r = client.get("/vms/", headers=auth_header)
    assert r.status_code == 200
    assert any(x["id"] == vm_id for x in r.json())

    # Delete VM (stop)
    r = client.delete(f"/vms/{vm_id}", headers=auth_header)
    assert r.status_code == 200
    deleted = r.json()
    assert deleted["id"] == vm_id
    assert deleted["state"] in {"stopped", "running", "provisioning"}


def test_actions_stop_start_reboot(client: TestClient, auth_header, store_and_runner):
    # Create VM
    payload = {"vcpus": 2, "mem_mib": 512, "disk_gib": 10}
    r = client.post("/vms/", headers=auth_header, json=payload)
    assert r.status_code == 201
    vm_id = r.json()["id"]

    # Stop
    r = client.post(
        f"/vms/{vm_id}/actions", headers=auth_header, json={"action": "stop"}
    )
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"

    # Start (may return provisioning due to API semantics)
    r = client.post(
        f"/vms/{vm_id}/actions", headers=auth_header, json={"action": "start"}
    )
    assert r.status_code == 200
    assert r.json()["state"] in {"provisioning", "running"}

    # Reboot -> provisioning immediately
    r = client.post(
        f"/vms/{vm_id}/actions", headers=auth_header, json={"action": "reboot"}
    )
    assert r.status_code == 200
    assert r.json()["state"] == "provisioning"


def test_upload_files_and_dirs_endpoints(
    client: TestClient, auth_header, monkeypatch, store_and_runner
):
    # Create VM
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    # Mock send_files
    def _fake_send_files(vm, files):
        return models.ElementResponse(ok=True)

    monkeypatch.setattr(vms, "send_files", _fake_send_files)

    body = {
        "dest_path": "/app",
        "files": [{"path": "hello.txt", "text": "world", "mode": 420}],
        "clean": True,
    }
    r = client.post(f"/vms/{vm_id}/upload-files", headers=auth_header, json=body)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "reason": ""}

    # Mock list_dirs
    def _fake_list_dirs(vm, paths, depth):
        return [
            {"path": "/app", "name": "app", "path_type": "directory"},
            {"path": "/app/hello.txt", "name": "hello.txt", "path_type": "file"},
        ]

    monkeypatch.setattr(vms, "list_dirs", _fake_list_dirs)

    r = client.post(
        f"/vms/{vm_id}/list-dirs",
        headers=auth_header,
        json={"paths": ["/app"], "depth": 1},
    )
    assert r.status_code == 200
    items = r.json()
    assert any(it["name"] == "hello.txt" for it in items)

    # Mock read_file
    def _fake_read_file(vm, path):
        return models.FileContent(
            name="hello.txt", content="world", length=5, found=True
        )

    monkeypatch.setattr(vms, "read_file", _fake_read_file)
    r = client.post(
        f"/vms/{vm_id}/read-file", headers=auth_header, json={"path": "/app/hello.txt"}
    )
    assert r.status_code == 200
    assert r.json()["found"] is True
    assert r.json()["content"] == "world"

    # Mock create_dir
    def _fake_create_dir(vm, path):
        return models.ElementResponse(ok=True, reason="")

    monkeypatch.setattr(vms, "create_dir", _fake_create_dir)
    r = client.post(
        f"/vms/{vm_id}/create-dir", headers=auth_header, json={"path": "/app/newdir"}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_search_in_vm(client: TestClient, auth_header, monkeypatch):
    # Create VM
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    # Mock SSH for search
    def _fake_cache(vm):
        cli = FakeSSHClient(
            stdout_data=b"/app/a.txt:1:hello\n/app/b.txt:2:world\n",
            stderr_data=b"",
        )
        return {"cli": cli}

    monkeypatch.setattr(vms, "cache_ssh_and_sftp", _fake_cache)
    body = {
        "pattern": "o",
        "root": "/app",
        "case_insensitive": False,
        "include_globs": ["*.txt"],
        "exclude_dirs": [".git"],
        "max_results_total": 10,
        "timeout_seconds": 2,
    }
    r = client.post(f"/vms/{vm_id}/search", headers=auth_header, json=body)
    assert r.status_code == 200
    hits = r.json()
    # Should aggregate by file
    paths = {h["path"] for h in hits}
    assert "/app/a.txt" in paths
    assert "/app/b.txt" in paths
    total = sum(len(h["matchs"]) for h in hits)
    assert total == 2

    # With limit 1
    body["max_results_total"] = 1
    r = client.post(f"/vms/{vm_id}/search", headers=auth_header, json=body)
    hits = r.json()
    total = sum(len(h["matchs"]) for h in hits)
    assert total == 1


def test_execute_sh(client: TestClient, auth_header, monkeypatch):
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    # Mock SSH for execute_sh
    def _fake_cache(vm):
        cli = FakeSSHClient(stdout_data=b"ok\n", stderr_data=b"")
        return {"cli": cli}

    monkeypatch.setattr(vms, "cache_ssh_and_sftp", _fake_cache)
    r = client.post(
        f"/vms/{vm_id}/execute-sh", headers=auth_header, json={"command": "echo ok"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    reason = data.get("reason", "")
    assert (reason == "") or ("ok" in reason)


def test_download_file_and_folder(client: TestClient, auth_header, monkeypatch):
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    # Mock single file download
    def _fake_download_file(vm, path):
        return {
            "content": b"abc",
            "media_type": "text/plain",
            "headers": {"Content-Disposition": 'attachment; filename="file.txt"'},
        }

    monkeypatch.setattr(vms, "download_file", _fake_download_file)
    r = client.get(
        f"/vms/{vm_id}/download-file?path=/app/file.txt", headers=auth_header
    )
    assert r.status_code == 200
    assert r.content == b"abc"
    assert r.headers["content-type"].startswith("text/plain")
    assert "file.txt" in r.headers.get("content-disposition", "")

    # Mock folder archive download
    def _fake_download_folder(vm, root, prefer_fmt):
        return {
            "content": b"ZIPDATA",
            "media_type": "application/zip",
            "headers": {"Content-Disposition": 'attachment; filename="app.zip"'},
        }

    monkeypatch.setattr(vms, "download_folder", _fake_download_folder)
    r = client.get(
        f"/vms/{vm_id}/download-folder?root=/app&prefer_fmt=zip", headers=auth_header
    )
    assert r.status_code == 200
    assert r.content == b"ZIPDATA"
    assert r.headers["content-type"].startswith("application/zip")


def test_websocket_tty_echo(client: TestClient, store_and_runner):
    store, runner, base_dir = store_and_runner

    # Manually create a VM to ensure running state and SSH fields for /tty
    vm_id = "ws-vm-1"
    wd = runner.workdir(vm_id)
    vm = models.VMRecord(
        id=vm_id,
        state=models.VMState.running,
        workdir=wd,
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
        ssh_port=2222,
        ssh_user="root",
        proc=models.VMProc(
            workdir=wd,
            overlay=os.path.join(wd, "disk.qcow2"),
            seed_iso=os.path.join(wd, "seed.iso"),
            port_ssh=2222,
            proc=None,
            console_log=os.path.join(wd, "console.log"),
            pidfile=os.path.join(wd, "qemu.pid"),
        ),
    )
    store.put(vm)

    with client.websocket_connect(f"/vms/{vm_id}/tty") as ws:
        ws.send_text("hello")
        msg = ws.receive_text()
        # WS handler appends newline if not present before calling bridge.send
        assert msg in ("REMOTE:hello", "REMOTE:hello\n")


def test_metrics_endpoint(
    client: TestClient, auth_header, store_and_runner, monkeypatch
):
    store, runner, base_dir = store_and_runner

    vm_id = "metrics-vm"
    wd = runner.workdir(vm_id)
    vm = models.VMRecord(
        id=vm_id,
        state=models.VMState.running,
        workdir=wd,
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
    )
    store.put(vm)

    pidfile = os.path.join(base_dir, "vms", vm_id, "qemu.pid")
    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    with open(pidfile, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    class FakePsutilProcess:
        def __init__(self, pid):
            self.pid = pid

        def cpu_percent(self, interval=None):
            return 12.5

        def memory_info(self):
            return types.SimpleNamespace(rss=10 * 1024 * 1024)

        def num_threads(self):
            return 7

        def io_counters(self):
            return types.SimpleNamespace(
                _asdict=lambda: {"read_count": 1, "write_count": 2}
            )

    # Patch psutil.Process used by metrics
    import psutil  # noqa: F401

    monkeypatch.setattr("routes.metrics.psutil.Process", FakePsutilProcess)

    r = client.get(f"/metrics/{vm_id}", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert data["cpu_percent"] == pytest.approx(12.5)
    assert data["rss_mib"] == pytest.approx(10.0, rel=1e-3)
    assert data["num_threads"] == 7
    assert "io" in data and isinstance(data["io"], dict)
