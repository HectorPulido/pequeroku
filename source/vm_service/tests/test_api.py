import os
import sys
import time
import types
import pathlib
from contextlib import contextmanager

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

    def stop(
        self,
        vm: models.VMRecord,
        cleanup_disks: bool = False,
        clear_port: bool = True,
    ) -> None:
        if clear_port:
            vm.ssh_port = None
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

    def recv_exit_status(self) -> int:
        return 0


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


def _fake_borrow(cli=None, sftp=None):
    """Build a fake ssh_pool.borrow that yields a connection with the given cli/sftp."""

    @contextmanager
    def _cm(container):
        yield types.SimpleNamespace(cli=cli, sftp=sftp)

    return _cm


class FakeTTYBridge:
    def __init__(self, ws, vm, loop=None):
        self.ws = ws
        self.vm = vm
        self.loop = loop
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


def test_ensure_vm_recreates_missing_record(
    client: TestClient, auth_header, store_and_runner
):
    store, _runner, _base_dir = store_and_runner
    vm_id = "11111111-1111-1111-1111-111111111111"

    # Record does not exist yet -> get returns 404
    r = client.get(f"/vms/{vm_id}", headers=auth_header)
    assert r.status_code == 404

    # Ensure rebuilds it (in 'stopped' state) from the provided specs
    payload = {"vcpus": 4, "mem_mib": 1024, "disk_gib": 20}
    r = client.post(f"/vms/{vm_id}/ensure", headers=auth_header, json=payload)
    assert r.status_code == 200
    ensured = r.json()
    assert ensured["id"] == vm_id
    assert ensured["state"] == "stopped"

    # The record now exists in the store with the requested specs
    rec = store.get(vm_id)
    assert rec.vcpus == 4
    assert rec.mem_mib == 1024
    assert rec.disk_gib == 20

    # And it is now retrievable through the regular endpoint (no more 404)
    r = client.get(f"/vms/{vm_id}", headers=auth_header)
    assert r.status_code == 200


def test_ensure_vm_is_idempotent(client: TestClient, auth_header, store_and_runner):
    # Create a VM the normal way
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 2, "mem_mib": 512, "disk_gib": 10}
    )
    vm_id = r.json()["id"]

    # Ensure with different specs must NOT clobber the existing record
    r = client.post(
        f"/vms/{vm_id}/ensure",
        headers=auth_header,
        json={"vcpus": 8, "mem_mib": 4096, "disk_gib": 50},
    )
    assert r.status_code == 200
    assert r.json()["id"] == vm_id


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

    # Mock SSH for search (the route borrows a pooled connection)
    cli = FakeSSHClient(
        stdout_data=b"/app/a.txt:1:hello\n/app/b.txt:2:world\n",
        stderr_data=b"",
    )
    monkeypatch.setattr(vms, "borrow", _fake_borrow(cli=cli))
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

    # Mock SSH for execute_sh (the route borrows a pooled connection)
    cli = FakeSSHClient(stdout_data=b"ok\n", stderr_data=b"")
    monkeypatch.setattr(vms, "borrow", _fake_borrow(cli=cli))
    r = client.post(
        f"/vms/{vm_id}/execute-sh", headers=auth_header, json={"command": "echo ok"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # The exit status is now part of the contract (captured via recv_exit_status).
    assert data["exit_code"] == 0
    reason = data.get("reason", "")
    assert (reason == "") or ("ok" in reason)


def test_listening_ports_endpoint(client: TestClient, auth_header, monkeypatch):
    import importlib

    # NB: `from implementations import listening_ports` yields the *function*
    # (re-exported in __init__), not the module. Grab the module to patch its
    # `borrow` global that the function calls.
    lp_mod = importlib.import_module("implementations.listening_ports")

    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    # `ss -ltnpH` style output: ssh on 22 (filtered), a loopback dev server, a
    # wildcard api, the IPv6 duplicate of ssh (also filtered), and the systemd
    # resolver noise on :53/:5355 (filtered by port + process).
    ss_out = (
        b'LISTEN 0 128   0.0.0.0:22    0.0.0.0:*  users:(("sshd",pid=600,fd=3))\n'
        b'LISTEN 0 511 127.0.0.1:3000  0.0.0.0:*  users:(("node",pid=1234,fd=20))\n'
        b'LISTEN 0 128      [::]:22       [::]:*  users:(("sshd",pid=600,fd=4))\n'
        b'LISTEN 0 511         *:8000        *:*  users:(("python3",pid=2345,fd=6))\n'
        b'LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=300,fd=18))\n'
        b'LISTEN 0 4096   127.0.0.1:5355 0.0.0.0:* users:(("systemd-resolve",pid=300,fd=10))\n'
    )
    cli = FakeSSHClient(stdout_data=ss_out)
    monkeypatch.setattr(lp_mod, "borrow", _fake_borrow(cli=cli))

    r = client.get(f"/vms/{vm_id}/listening-ports", headers=auth_header)
    assert r.status_code == 200
    ports = r.json()
    by_port = {p["port"]: p for p in ports}

    assert 22 not in by_port  # SSH is filtered out
    assert 53 not in by_port and 5355 not in by_port  # systemd-resolved noise gone
    assert [p["port"] for p in ports] == [3000, 8000]  # deduped + sorted
    assert by_port[3000]["process"] == "node"
    assert by_port[3000]["pid"] == 1234
    assert by_port[3000]["address"] == "127.0.0.1"
    assert by_port[8000]["process"] == "python3"


def test_parse_ss_dedup_and_wildcard():
    from implementations.listening_ports import _parse_ss

    text = (
        'LISTEN 0 511 127.0.0.1:5000 0.0.0.0:* users:(("flask",pid=10,fd=3))\n'
        "LISTEN 0 511   0.0.0.0:5000 0.0.0.0:*\n"  # same port, wildcard, no process
        'LISTEN 0 128      [::]:9229    [::]:* users:(("node",pid=7,fd=9))\n'
        'LISTEN 0 128 127.0.0.1:11323 0.0.0.0:* users:(("chronyd",pid=99,fd=5))\n'  # system proc
        "\n"  # blank line ignored
        "garbage line without colon port\n"  # malformed, ignored
    )
    ports = _parse_ss(text)
    by_port = {p.port: p for p in ports}

    # 11323 dropped: chronyd is a system daemon even though the port isn't hidden.
    assert 11323 not in by_port
    assert sorted(by_port) == [5000, 9229]
    # Port 5000 seen twice: keep the process learned from the loopback row, but
    # display the wildcard bind address.
    assert by_port[5000].process == "flask"
    assert by_port[5000].address == "0.0.0.0"
    # IPv6 brackets stripped.
    assert by_port[9229].address == "::"
    assert by_port[9229].process == "node"


def test_build_forward_headers():
    from implementations.preview_proxy import build_forward_headers

    fwd = build_forward_headers(
        {
            "Accept": "text/html",
            "Connection": "keep-alive",  # hop-by-hop -> dropped
            "Host": "evil.example",  # overridden
            "Accept-Encoding": "gzip",  # overridden to identity
            "Content-Length": "5",  # dropped (http.client recomputes)
            "X-Custom": "keep-me",
        },
        8000,
    )
    assert fwd["Host"] == "127.0.0.1:8000"
    assert fwd["Accept-Encoding"] == "identity"
    assert fwd["Connection"] == "close"
    assert fwd["Accept"] == "text/html"
    assert fwd["X-Custom"] == "keep-me"
    assert "keep-alive" not in fwd.values()
    assert "Content-Length" not in fwd


def test_proxy_endpoint_and_ssrf_guard(client: TestClient, auth_header, monkeypatch):
    r = client.post(
        "/vms/", headers=auth_header, json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5}
    )
    vm_id = r.json()["id"]

    captured = {}

    def _fake_proxy(vm, req):
        captured["port"] = req.target_port
        captured["method"] = req.method
        captured["path"] = req.path
        return models.VMProxyResponse(
            ok=True,
            status=200,
            headers=[("Content-Type", "application/json")],
            body_b64="b2s=",  # "ok"
        )

    monkeypatch.setattr(vms, "proxy_request", _fake_proxy)

    body = {"target_port": 8000, "method": "GET", "path": "/openapi.json"}
    r = client.post(f"/vms/{vm_id}/proxy", headers=auth_header, json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True and data["status"] == 200
    assert captured == {"port": 8000, "method": "GET", "path": "/openapi.json"}

    # SSRF guard: sshd and out-of-range ports are rejected before proxying.
    r = client.post(
        f"/vms/{vm_id}/proxy", headers=auth_header, json={"target_port": 22}
    )
    assert r.status_code == 400
    r = client.post(f"/vms/{vm_id}/proxy", headers=auth_header, json={"target_port": 0})
    assert r.status_code == 400

    # Missing VM -> 404
    r = client.post(
        "/vms/does-not-exist/proxy", headers=auth_header, json={"target_port": 8000}
    )
    assert r.status_code == 404


def test_proxy_request_parses_buffered_response(monkeypatch):
    import base64 as _b64
    from contextlib import contextmanager
    import implementations.preview_proxy as pp

    response_bytes = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 13\r\n"
        b"\r\n"
        b'{"ok": true}\n'
    )

    class FakeChan:
        def __init__(self):
            self.sent = b""
            self._served = False

        def settimeout(self, t):
            pass

        def sendall(self, data):
            self.sent += data

        def recv(self, n):
            if self._served:
                return b""
            self._served = True
            return response_bytes

        def close(self):
            pass

    chan = FakeChan()

    class FakeTransport:
        def open_channel(self, kind, dest, src):
            assert kind == "direct-tcpip"
            assert dest == ("127.0.0.1", 8000)
            return chan

    class FakeCli:
        def get_transport(self):
            return FakeTransport()

    @contextmanager
    def fake_borrow(container):
        yield FakeCli()

    monkeypatch.setattr(pp, "borrow_preview", fake_borrow)

    vm = models.VMRecord(
        id="vm1",
        state=models.VMState.running,
        workdir="/tmp",
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
        ssh_port=2222,
        ssh_user="root",
    )
    req = models.VMProxyRequest(target_port=8000, method="GET", path="/openapi.json")
    resp = pp.proxy_request(vm, req)

    assert resp.ok is True
    assert resp.status == 200
    assert _b64.b64decode(resp.body_b64) == b'{"ok": true}\n'  # binary-safe, verbatim
    # The raw request carried our pinned headers.
    assert b"GET /openapi.json HTTP/1.1" in chan.sent
    assert b"Host: 127.0.0.1:8000" in chan.sent
    assert b"Connection: close" in chan.sent
    hdrs = {k.lower(): v for k, v in resp.headers}
    assert hdrs.get("content-type") == "application/json"


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


def test_duplicate_endpoint_copies_disk(client, auth_header, store_and_runner):
    store, runner, base_dir = store_and_runner

    # A stopped source VM with a disk on disk.
    src_id = "dup-src"
    wd = runner.workdir(src_id)
    with open(os.path.join(wd, "disk.qcow2"), "wb") as f:
        f.write(b"QCOW2-FAKE-DISK-DELTA")
    store.put(
        models.VMRecord(
            id=src_id,
            state=models.VMState.stopped,
            workdir=wd,
            vcpus=1,
            mem_mib=256,
            disk_gib=5,
        )
    )

    r = client.post(
        f"/vms/{src_id}/duplicate",
        headers=auth_header,
        json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5, "start": True},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    new_id = data["id"]
    assert new_id != src_id

    # The new VM's disk is a byte-for-byte copy of the source overlay.
    new_disk = os.path.join(base_dir, "vms", new_id, "disk.qcow2")
    assert os.path.exists(new_disk)
    with open(new_disk, "rb") as f:
        assert f.read() == b"QCOW2-FAKE-DISK-DELTA"
    # And the source disk is untouched.
    with open(os.path.join(wd, "disk.qcow2"), "rb") as f:
        assert f.read() == b"QCOW2-FAKE-DISK-DELTA"


def test_duplicate_endpoint_missing_disk(client, auth_header, store_and_runner):
    store, runner, base_dir = store_and_runner

    src_id = "dup-nodisk"
    runner.workdir(src_id)  # workdir exists but no disk.qcow2

    r = client.post(
        f"/vms/{src_id}/duplicate",
        headers=auth_header,
        json={"vcpus": 1, "mem_mib": 256, "disk_gib": 5},
    )
    assert r.status_code == 404
