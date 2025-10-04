import base64
import types
import time
import errno

import models
from implementations import send_file as sf


class DummyChannel:
    def __init__(self, status: int = 0):
        self._status = status

    def recv_exit_status(self):
        return self._status


class DummyFile:
    def __init__(self, data: bytes = b"", status: int = 0):
        self._data = data
        self.channel = DummyChannel(status=status)

    def read(self) -> bytes:
        return self._data


class DummyCLI:
    """
    Minimal CLI that returns given status and buffers.
    """

    def __init__(self, status: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
        self.last_command = None

    def exec_command(self, cmd: str, timeout=None):
        self.last_command = cmd
        return (
            None,
            DummyFile(self.stdout, status=self.status),
            DummyFile(self.stderr, status=self.status),
        )


class MemSFTPWriter:
    def __init__(self, store: dict, path: str):
        self._store = store
        self._path = path
        self._buf = bytearray()

    def write(self, data: bytes):
        self._buf.extend(data)

    def close(self):
        self._store[self._path] = bytes(self._buf)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class MemSFTP:
    """
    Simple in-memory SFTP engine for tests.
    """

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.made_dirs: list[str] = []
        self.chmod_calls: list[tuple[str, int]] = []
        self.raise_chmod = False

    def file(self, path: str, mode: str = "rb"):
        data = self.files.get(path, b"")
        return types.SimpleNamespace(read=lambda: data)

    def open(self, path: str, mode: str = "wb"):
        return MemSFTPWriter(self.files, path)

    def stat(self, path: str):
        # Only known paths in files are files; any other returns not found
        if path in self.files:
            return types.SimpleNamespace(st_mode="100644")
        # treat explicitly created dirs as present
        if path in self.made_dirs:
            return types.SimpleNamespace(st_mode="040000")
        # not found
        raise OSError(errno.ENOENT, "not found")

    def normalize(self, path: str):
        if not path:
            return "/"
        if not path.startswith("/"):
            return "/" + path
        return path

    def mkdir(self, path: str):
        if path not in self.made_dirs:
            self.made_dirs.append(path)

    def chmod(self, path: str, mode: int):
        if self.raise_chmod:
            raise RuntimeError("chmod not supported")
        self.chmod_calls.append((path, mode))


def make_vm(tmp_path) -> models.VMRecord:
    return models.VMRecord(
        id="vm-x",
        state=models.VMState.running,
        workdir=str(tmp_path / "vm"),
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
        ssh_port=2222,
        ssh_user="root",
    )


def test_send_files_no_sftp_ready(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)

    # open_ssh_and_sftp returns (None, None) so _prepare_vm_for_transfer -> (None, None, None)
    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (None, None))

    files = models.VMUploadFiles(
        dest_path="/app",
        files=[models.VMFile(path="a.txt", text="hello", mode=0o644)],
        clean=True,
    )

    resp = sf.send_files(vm, files)
    assert resp.ok is False
    assert "No sftp ready" in resp.reason


def test_prepare_vm_clean_calls_clean_dest(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    sftp = MemSFTP()
    cli = DummyCLI()

    called = {"args": None}

    def _clean_dest_spy(cli_arg, dest_path):
        called["args"] = (cli_arg, dest_path)

    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (sftp, cli))
    monkeypatch.setattr(sf, "_clean_dest", _clean_dest_spy)
    # avoid sleeps inside _save_file_bytes even though we won't reach it
    monkeypatch.setattr(time, "sleep", lambda x: None)

    files = models.VMUploadFiles(dest_path="/app", files=[], clean=True)
    resp = sf.send_files(vm, files)
    assert resp.ok is True
    assert called["args"] == (cli, "/app")


def test_prepare_vm_not_clean_mkdir(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    sftp = MemSFTP()
    cli = DummyCLI()

    cmds = []

    def _run_and_check_spy(cli_arg, cmd: str, timeout=None):
        cmds.append(cmd)

    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (sftp, cli))
    monkeypatch.setattr(sf, "_run_and_check", _run_and_check_spy)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    files = models.VMUploadFiles(dest_path="/app", files=[], clean=False)
    resp = sf.send_files(vm, files)
    assert resp.ok is True
    assert any(cmd.startswith("mkdir -p ") for cmd in cmds)


def test_norm_join_security_violation(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    sftp = MemSFTP()
    cli = DummyCLI()

    saved = {"calls": 0}

    def _save_file_bytes_spy(sftp_arg, cli_arg, full_path, data, file_mode):
        saved["calls"] += 1  # count successful saves

    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (sftp, cli))
    monkeypatch.setattr(sf, "_clean_dest", lambda c, d: None)
    monkeypatch.setattr(sf, "_save_file_bytes", _save_file_bytes_spy)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    up = models.VMUploadFiles(
        dest_path="/app",
        files=[
            models.VMFile(path="ok/hello.txt", text="hi", mode=0o644),
            models.VMFile(path="../etc/passwd", text="oops", mode=0o644),
        ],
        clean=True,
    )
    resp = sf.send_files(vm, up)
    assert resp.ok is False
    assert "Failed files:" in resp.reason
    assert "../etc/passwd" in resp.reason
    # Only the safe file should be attempted to save
    assert saved["calls"] == 1


def test_send_files_text_and_b64_and_chmod_fallback(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    sftp = MemSFTP()
    sftp.raise_chmod = True  # force fallback to remote chmod
    cli = DummyCLI()

    chmod_cmds = []

    def _run_and_check_spy(cli_arg, cmd: str, timeout=None):
        chmod_cmds.append(cmd)

    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (sftp, cli))
    monkeypatch.setattr(sf, "_clean_dest", lambda c, d: None)
    monkeypatch.setattr(sf, "_run_and_check", _run_and_check_spy)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    up = models.VMUploadFiles(
        dest_path="/app",
        files=[
            models.VMFile(path="a.txt", text="hola", mode=0o644),
            models.VMFile(
                path="b.txt",
                content_b64=base64.b64encode(b"mundo").decode(),
                mode=0o640,
            ),
        ],
        clean=True,
    )
    resp = sf.send_files(vm, up)
    assert resp.ok is True

    # Data written
    assert sftp.files.get("/app/a.txt") == b"hola"
    assert sftp.files.get("/app/b.txt") == b"mundo"

    # Fallback chmod via _run_and_check called for each file
    assert len(chmod_cmds) == 2
    assert any("chmod 0o644 /app/a.txt" in cmd for cmd in chmod_cmds)
    assert any("chmod 0o640 /app/b.txt" in cmd for cmd in chmod_cmds)


def test_create_dir_success(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    cli = DummyCLI(status=0)

    monkeypatch.setattr(sf, "open_ssh", lambda container: cli)

    resp = sf.create_dir(vm, "/data/new")
    assert resp.ok is True
    assert "mkdir -p" in cli.last_command


def test_create_dir_failure(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    # exit != 0 will cause _run_and_check to raise -> create_dir returns ok=False
    cli = DummyCLI(status=1, stderr=b"permission denied")
    monkeypatch.setattr(sf, "open_ssh", lambda container: cli)

    resp = sf.create_dir(vm, "/data/nope")
    assert resp.ok is False
    assert "Command failed" in resp.reason


def test_sftp_mkdirs_creates_nested(monkeypatch):
    sftp = MemSFTP()
    # Ensure stat on any path raises ENOENT so mkdirs are triggered
    created = []

    def mkdir_spy(path):
        created.append(path)
        return MemSFTP.mkdir(sftp, path)

    monkeypatch.setattr(sftp, "mkdir", mkdir_spy)

    sf._sftp_mkdirs(sftp, "/a/b/c")
    # Expect nested directories created in order
    assert "/a" in created
    assert "/a/b" in created
    assert "/a/b/c" in created


def test_send_files_collects_failed_files(monkeypatch, tmp_path):
    vm = make_vm(tmp_path)
    sftp = MemSFTP()
    cli = DummyCLI()

    def _save_file_bytes_conditional(sftp_arg, cli_arg, full_path, data, file_mode):
        if full_path.endswith("/bad.txt"):
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(sf, "open_ssh_and_sftp", lambda container: (sftp, cli))
    monkeypatch.setattr(sf, "_clean_dest", lambda c, d: None)
    monkeypatch.setattr(sf, "_save_file_bytes", _save_file_bytes_conditional)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    up = models.VMUploadFiles(
        dest_path="/app",
        files=[
            models.VMFile(path="good.txt", text="ok", mode=0o644),
            models.VMFile(path="bad.txt", text="fail", mode=0o644),
        ],
        clean=True,
    )
    resp = sf.send_files(vm, up)
    assert resp.ok is False
    assert "Failed files:" in resp.reason
    assert "bad.txt" in resp.reason
