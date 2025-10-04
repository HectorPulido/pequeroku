import types
import pytest

import models
import implementations.ssh_cache as sc


class FakeChannel:
    def __init__(self):
        self.closed = False
        self._timeout = None

    def settimeout(self, t):
        self._timeout = t


class FakeSFTPClient:
    pass


class FakeSSHClient:
    def __init__(self):
        self._policy = None
        self.connected = False
        self.connect_args = {}
        self.exec_calls = []
        self.raise_on_exec = False
        self.channels_created = 0
        self._sftp = FakeSFTPClient()

    def set_missing_host_key_policy(self, policy):
        self._policy = policy

    def connect(self, hostname, port, username, pkey, look_for_keys):
        self.connected = True
        self.connect_args = {
            "hostname": hostname,
            "port": port,
            "username": username,
            "pkey": pkey,
            "look_for_keys": look_for_keys,
        }

    def open_sftp(self):
        return self._sftp

    def exec_command(self, command: str):
        self.exec_calls.append(command)
        if self.raise_on_exec:
            raise RuntimeError("boom")
        # Minimal tuple-like expected by callers; they don't use the streams here
        return None, None, None

    def invoke_shell(self, width=120, height=32):
        self.channels_created += 1
        ch = FakeChannel()
        return ch


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    # Reset cache per test to isolate
    monkeypatch.setattr(sc, "cache_data", {})


@pytest.fixture
def fake_paramiko(monkeypatch):
    class DummyEd25519:
        @staticmethod
        def from_private_key_file(path):
            # any opaque object is fine
            return object()

    class DummyPolicy:
        pass

    monkeypatch.setattr(sc.paramiko, "Ed25519Key", DummyEd25519, raising=True)
    monkeypatch.setattr(
        sc.paramiko, "AutoAddPolicy", lambda: DummyPolicy(), raising=True
    )
    monkeypatch.setattr(sc.paramiko, "SSHClient", FakeSSHClient, raising=True)
    return FakeSSHClient


@pytest.fixture
def vm_record():
    return models.VMRecord(
        id="vm-1",
        state=models.VMState.running,
        workdir="/tmp",
        vcpus=1,
        mem_mib=256,
        disk_gib=5,
        ssh_port=2222,
        ssh_user="root",
    )


def test_cache_generate_by_id(monkeypatch, fake_paramiko):
    # Ensure key path exists logically (we don't read it)
    monkeypatch.setattr(sc.settings, "VM_SSH_PRIVKEY", "/fake/key", raising=False)

    out = sc.cache_ssh_and_sftp_by_id("abc", 2222, "root")
    assert "abc" in sc.cache_data
    assert isinstance(out.get("cli"), FakeSSHClient)
    assert isinstance(out.get("sftp"), FakeSFTPClient)
    assert isinstance(out.get("chan"), FakeChannel)

    cli: FakeSSHClient = out["cli"]  # type: ignore[assignment]
    assert cli.connected is True
    assert cli.connect_args["hostname"] == "127.0.0.1"
    assert cli.connect_args["port"] == 2222
    assert cli.connect_args["username"] == "root"
    # A channel was created as part of initial generation
    assert cli.channels_created == 1


def test_cache_reuse_when_valid(monkeypatch, fake_paramiko):
    # Preload cache with valid entries
    cli = FakeSSHClient()
    sftp = FakeSFTPClient()
    sc.cache_data["id1"] = {"cli": cli, "sftp": sftp}

    # If generator is called, raise to detect unexpected regeneration
    def _unexpected(*args, **kwargs):
        raise AssertionError("Generator should not be called for valid cache")

    monkeypatch.setattr(sc, "_generate_ssh_and_sftp_by_id", _unexpected, raising=True)

    data = sc.cache_ssh_and_sftp_by_id("id1", 22, "root")
    assert data["cli"] is cli
    assert data["sftp"] is sftp
    # Validity check should call exec_command once
    assert cli.exec_calls == ["echo hello"]


def test_cache_regenerate_when_missing_cli(monkeypatch, fake_paramiko):
    # Missing 'cli' should force regeneration
    sc.cache_data["id2"] = {"sftp": FakeSFTPClient()}

    called = {"times": 0}

    def _generator(container_id, ssh_port, ssh_user):
        called["times"] += 1
        c = FakeSSHClient()
        s = c.open_sftp()
        ch = c.invoke_shell(width=120, height=32)
        ch.settimeout(0.0)
        sc.cache_data[container_id] = {"cli": c, "sftp": s, "chan": ch}
        return c, s, ch

    monkeypatch.setattr(sc, "_generate_ssh_and_sftp_by_id", _generator, raising=True)
    data = sc.cache_ssh_and_sftp_by_id("id2", 2222, "root")
    assert called["times"] == 1
    assert isinstance(data["cli"], FakeSSHClient)
    assert isinstance(data["sftp"], FakeSFTPClient)
    assert isinstance(data["chan"], FakeChannel)


def test_cache_regenerate_when_missing_sftp(monkeypatch, fake_paramiko):
    sc.cache_data["id3"] = {"cli": FakeSSHClient()}

    called = {"times": 0}

    def _generator(container_id, ssh_port, ssh_user):
        called["times"] += 1
        c = FakeSSHClient()
        s = c.open_sftp()
        ch = c.invoke_shell(width=120, height=32)
        ch.settimeout(0.0)
        sc.cache_data[container_id] = {"cli": c, "sftp": s, "chan": ch}
        return c, s, ch

    monkeypatch.setattr(sc, "_generate_ssh_and_sftp_by_id", _generator, raising=True)
    data = sc.cache_ssh_and_sftp_by_id("id3", 2222, "root")
    assert called["times"] == 1
    assert isinstance(data["cli"], FakeSSHClient)
    assert isinstance(data["sftp"], FakeSFTPClient)


def test_cache_regenerate_when_exec_command_raises(monkeypatch, fake_paramiko):
    bad_cli = FakeSSHClient()
    bad_cli.raise_on_exec = True
    sc.cache_data["id4"] = {"cli": bad_cli, "sftp": FakeSFTPClient()}

    called = {"times": 0}

    def _generator(container_id, ssh_port, ssh_user):
        called["times"] += 1
        c = FakeSSHClient()
        s = c.open_sftp()
        ch = c.invoke_shell(width=120, height=32)
        ch.settimeout(0.0)
        sc.cache_data[container_id] = {"cli": c, "sftp": s, "chan": ch}
        return c, s, ch

    monkeypatch.setattr(sc, "_generate_ssh_and_sftp_by_id", _generator, raising=True)
    data = sc.cache_ssh_and_sftp_by_id("id4", 22, "root")
    assert called["times"] == 1
    assert isinstance(data["cli"], FakeSSHClient)
    assert data["cli"] is not bad_cli  # replaced


def test_open_helpers_and_generate_console(monkeypatch, fake_paramiko, vm_record):
    monkeypatch.setattr(sc.settings, "VM_SSH_PRIVKEY", "/fake/key", raising=False)

    # First call will generate and populate cache
    cli = sc.open_ssh(vm_record)
    sftp = sc.open_sftp(vm_record)
    assert isinstance(cli, FakeSSHClient)
    assert isinstance(sftp, FakeSFTPClient)

    # After generation, initial channel was created
    assert cli.channels_created == 1

    # open_ssh_and_sftp returns the same instances in order (sftp, cli)
    s, c = sc.open_ssh_and_sftp(vm_record)
    assert s is sftp
    assert c is cli

    # generate_console should create a NEW channel (not from cache)
    c2, chan = sc.generate_console(vm_record)
    assert c2 is cli
    assert isinstance(chan, FakeChannel)
    assert cli.channels_created == 2
    assert chan._timeout == 0.0  # generate_console sets non-blocking timeout


def test_clear_cache_and_clear_all(monkeypatch, fake_paramiko):
    # Populate some entries
    sc.cache_data["x"] = {"cli": FakeSSHClient(), "sftp": FakeSFTPClient()}
    sc.cache_data["y"] = {"cli": FakeSSHClient(), "sftp": FakeSFTPClient()}

    sc.clear_cache("x")
    assert sc.cache_data.get("x") == {}

    sc.clear_all_cache()
    assert sc.cache_data == {}
