import types
import pytest

import models
import implementations.read_from_vm as read_from_vm


class FakeSFTPFile:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSFTP:
    def __init__(
        self, files: dict[str, bytes] | None = None, dirs: set[str] | None = None
    ):
        # files maps absolute path -> bytes
        self._files = files or {}
        # dirs is a set of absolute dir paths (no trailing slash enforced)
        self._dirs = {d.rstrip("/") for d in (dirs or set())}

    # read_from_vm uses `.file(path, "rb")` as context manager
    def file(self, path: str, mode: str = "rb"):
        if path not in self._files:
            raise FileNotFoundError(path)
        return FakeSFTPFile(self._files[path])

    # read_from_vm uses `.open(path, "wb")` in send_file module, not here, but leave minimal stub
    def open(self, path: str, mode: str = "wb"):
        return FakeSFTPFile(b"")

    def stat(self, path: str):
        # simulate directory if path is in dirs
        norm = path.rstrip("/")
        if norm in self._dirs:
            return types.SimpleNamespace(st_mode="040000")  # directory
        if path in self._files:
            return types.SimpleNamespace(st_mode="100644")  # regular file
        # treat unknown path as not found
        raise FileNotFoundError(path)

    def normalize(self, path: str):
        if not path.startswith("/"):
            return "/" + path
        return path

    def mkdir(self, path: str):
        self._dirs.add(path.rstrip("/"))

    def chmod(self, path: str, mode: int):
        return None


class FakeStdout:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeSSH:
    def __init__(
        self,
        responses: dict[str, tuple[bytes, bytes]] | None = None,
        default: tuple[bytes, bytes] = (b"", b""),
    ):
        """
        responses: maps a substring key to (stdout, stderr) bytes. First matching substring in command wins.
        default: returned if no key matches.
        """
        self._responses = responses or {}
        self._default = default

    def exec_command(self, command: str):
        for key, (out, err) in self._responses.items():
            if key in command:
                return None, FakeStdout(out), FakeStdout(err)
        return None, FakeStdout(self._default[0]), FakeStdout(self._default[1])


@pytest.fixture
def vm_record(tmp_path):
    return models.VMRecord(
        id="vm-test",
        state=models.VMState.running,
        workdir=str(tmp_path / "vm"),
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
        ssh_port=2222,
        ssh_user="root",
    )


def test_list_dirs_parses_find_output(monkeypatch, vm_record):
    # Simulate the `find` output: path||type-char
    stdout = (
        b"/app||d\n"
        b"/app/dir1||d\n"
        b"/app/dir1/file1.txt||f\n"
        b"/app/file2.log||f\n"
    )
    cli = FakeSSH(responses={"find ": (stdout, b"")})

    # Patch open_ssh to return our fake cli
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    items = read_from_vm.list_dirs(vm_record, ["/app"], depth=2)
    # Ensure items include directory and file entries with proper names and path types
    paths = {it.path for it in items}
    assert "/app" in paths
    assert "/app/dir1" in paths
    assert "/app/dir1/file1.txt" in paths
    assert "/app/file2.log" in paths

    # Verify name and path_type mapping roughly (pick one sample)
    dic = {it.path: it for it in items}
    assert dic["/app"].name == "app"
    assert dic["/app"].path_type in ("directory", "file")  # derived from 'd'/'f'
    assert dic["/app/dir1/file1.txt"].name == "file1.txt"


def test_list_dir_single_path(monkeypatch, vm_record):
    stdout = b"/home||d\n/home/readme.md||f\n"
    cli = FakeSSH(responses={"find ": (stdout, b"")})
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    items = read_from_vm.list_dir(vm_record, "/home")
    names = {it.name for it in items}
    assert "home" in names
    assert "readme.md" in names


def test_read_file_found(monkeypatch, vm_record):
    sftp = FakeSFTP(files={"/etc/hosts": b"127.0.0.1 localhost\n"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    content = read_from_vm.read_file(vm_record, "/etc/hosts")
    assert content.found is True
    assert "localhost" in content.content
    assert content.name == "hosts"


def test_read_file_not_found(monkeypatch, vm_record):
    sftp = FakeSFTP(files={})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    content = read_from_vm.read_file(vm_record, "/no/such/file.txt")
    assert content.found is False
    assert content.content == ""
    assert content.name == "file.txt"


def test_download_file_success(monkeypatch, vm_record):
    sftp = FakeSFTP(files={"/app/hello.txt": b"hello world"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    resp = read_from_vm.download_file(vm_record, "/app/hello.txt")
    assert resp is not None
    assert resp["content"] == b"hello world"
    assert resp["media_type"] in ("text/plain", "application/octet-stream")
    assert "hello.txt" in resp["headers"].get("Content-Disposition", "")


def test_download_file_not_found(monkeypatch, vm_record):
    sftp = FakeSFTP(files={})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    assert read_from_vm.download_file(vm_record, "/app/missing.txt") is None


def test_download_file_is_directory(monkeypatch, vm_record):
    sftp = FakeSFTP(files={}, dirs={"/app/somedir"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    assert read_from_vm.download_file(vm_record, "/app/somedir") is None


def test_download_folder_zip_success(monkeypatch, vm_record):
    # Pretend zip is available
    monkeypatch.setattr(read_from_vm, "_zip_available", lambda cli: True, raising=False)

    # Provide sftp that reports the directory exists
    sftp = FakeSFTP(files={}, dirs={"/app"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    # SSH returns non-empty stdout for the zip pack command
    cli = FakeSSH(responses={"zip -r - .": (b"ZIPDATA", b"")})
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    resp = read_from_vm.download_folder(vm_record, "/app", "zip")
    assert resp is not None
    assert resp["content"] == b"ZIPDATA"
    assert resp["media_type"] == "application/zip"
    assert 'filename="app.zip"' in resp["headers"].get("Content-Disposition", "")


def test_download_folder_tar_gz_when_zip_unavailable(monkeypatch, vm_record):
    # Force fallback to tar.gz
    monkeypatch.setattr(
        read_from_vm, "_zip_available", lambda cli: False, raising=False
    )

    sftp = FakeSFTP(files={}, dirs={"/data"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    cli = FakeSSH(responses={"tar -C": (b"TARDATA", b"")})
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    resp = read_from_vm.download_folder(vm_record, "/data", "zip")
    assert resp is not None
    assert resp["content"] == b"TARDATA"
    assert resp["media_type"] == "application/gzip"
    assert 'filename="data.tar.gz"' in resp["headers"].get("Content-Disposition", "")


def test_download_folder_missing_dir(monkeypatch, vm_record):
    sftp = FakeSFTP(files={}, dirs=set())
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    # open_ssh should not matter because it should fail before executing command
    cli = FakeSSH()
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    resp = read_from_vm.download_folder(vm_record, "/nope", "zip")
    assert resp is None


def test_download_folder_empty_output_returns_none(monkeypatch, vm_record):
    monkeypatch.setattr(read_from_vm, "_zip_available", lambda cli: True, raising=False)
    sftp = FakeSFTP(files={}, dirs={"/app"})
    monkeypatch.setattr(read_from_vm, "open_sftp", lambda vm: sftp, raising=False)

    # Command returns empty archive and an error message on stderr
    cli = FakeSSH(responses={"zip -r - .": (b"", b"some error")})
    monkeypatch.setattr(read_from_vm, "open_ssh", lambda vm: cli, raising=False)

    resp = read_from_vm.download_folder(vm_record, "/app", "zip")
    assert resp is None
