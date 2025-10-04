# conftest.py
import os
import sys
import time
import types
import pathlib
from typing import Tuple

import pytest
from fastapi.testclient import TestClient

# ----------------------
# Path setup: ensure vm_service package root is importable as top-level
# so imports like `import settings` resolve to vm_service/settings.py
# ----------------------
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_PKG_ROOT = _THIS_DIR.parent  # vm_service/
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# After adjusting sys.path, import project modules
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
        self.closed = False

    def settimeout(self, t):
        self._timeout = t

    def recv(self, n: int) -> bytes:
        return b""

    def send(self, data):
        return None

    def close(self):
        self.closed = True


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

    def open_sftp(self):
        # Minimal fake SFTP client with file/stat behavior
        class _SFTP:
            def __init__(self, files: dict[str, bytes] | None = None):
                self._files = files or {}
                self._cwd = "/"

            def file(self, path, mode="rb"):
                # Return a file-like that supports read()
                data = self._files.get(path, b"")
                return types.SimpleNamespace(read=lambda: data)

            def open(self, path, mode="wb"):
                # Return a writer that writes into our dict
                class _W:
                    def __init__(self, files: dict[str, bytes], p: str):
                        self._files = files
                        self._p = p
                        self._buf = bytearray()

                    def write(self, b: bytes):
                        self._buf.extend(b)

                    def close(self):
                        self._files[self._p] = bytes(self._buf)

                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        self.close()

                return _W(self._files, path)

            def stat(self, path):
                if path not in self._files and not path.endswith("/"):
                    raise FileNotFoundError(path)
                # Return a minimal object with st_mode
                # Use "100644"-like string for file and "4..."-ish for dir (simulate)
                is_dir = path.endswith("/")
                mode = 0o040000 if is_dir else 0o100644
                return types.SimpleNamespace(st_mode=str(mode))

            def normalize(self, path):
                if not path or not path.startswith("/"):
                    return "/" + (path or "")
                return path

            def mkdir(self, path):
                # No-op in fake
                return None

            def chmod(self, path, mode):
                # No-op in fake
                return None

        return _SFTP()

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
        self.started = True

    async def send(self, text: str):
        await self.ws.send_text(f"REMOTE:{text}")

    def close(self):
        self.closed = True


# ----------------------
# Shared Fixtures
# ----------------------
@pytest.fixture(autouse=True)
def patch_auth_token(monkeypatch):
    """
    Ensure AUTH_TOKEN is set for all tests.
    """
    monkeypatch.setattr(settings, "AUTH_TOKEN", "testtoken", raising=False)


@pytest.fixture
def auth_header():
    return {"Authorization": "Bearer testtoken"}


@pytest.fixture
def store_and_runner(tmp_path, monkeypatch) -> Tuple[InMemoryStore, FakeRunner, str]:
    """
    Provide an in-memory store and a fake runner patched into the app modules.
    Also set a VM_BASE_DIR in a temp path and make threading.Timer deterministic.
    """
    base_dir = tmp_path / "vm_data"
    os.makedirs(base_dir, exist_ok=True)

    test_store = InMemoryStore()
    test_runner = FakeRunner(test_store, "test-node", str(base_dir))

    # patch base dir for any file paths (console, pidfile, etc.)
    monkeypatch.setattr(settings, "VM_BASE_DIR", str(base_dir), raising=False)

    # patch store/runner in API modules
    monkeypatch.setattr(vms, "store", test_store, raising=False)
    monkeypatch.setattr(vms, "runner", test_runner, raising=False)
    monkeypatch.setattr(main, "store", test_store, raising=False)
    monkeypatch.setattr(main, "runner", test_runner, raising=False)

    # Make Timer act immediately for reboot actions
    import threading

    monkeypatch.setattr(threading, "Timer", FakeTimer, raising=True)

    return test_store, test_runner, str(base_dir)


@pytest.fixture
def client(store_and_runner, monkeypatch) -> TestClient:
    """
    FastAPI TestClient with the TTY bridge mocked out for deterministic behavior.
    """
    monkeypatch.setattr(main, "TTYBridge", FakeTTYBridge, raising=False)
    return TestClient(main.app)


@pytest.fixture
def fake_ssh_factory():
    """
    Helper factory to create FakeSSHClient instances with custom stdout/stderr.
    """

    def _make(stdout_data: bytes = b"", stderr_data: bytes = b"") -> FakeSSHClient:
        return FakeSSHClient(stdout_data=stdout_data, stderr_data=stderr_data)

    return _make
