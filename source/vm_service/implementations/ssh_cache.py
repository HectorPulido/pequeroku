from typing import cast
import shlex
import socket
import paramiko
import settings
from models import VMRecord
from qemu_manager.crypto import load_pkey

# Identity marker: each VM stamps its own vm_id into the guest at boot (see
# qemu_manager.ssh_ready.wait_ssh) so a consumer can verify the machine behind a
# loopback SSH port is really the VM it asked for — defending against ssh_port
# collisions that would otherwise route one container to another's VM.
VM_ID_MARKER_PATH = "/etc/pequeroku-vm-id"


class VMIdentityMismatch(Exception):
    """Raised when the VM behind an SSH port is not the vm_id we expected."""


cache_data: dict[
    str, dict[str, paramiko.SSHClient | paramiko.SFTPClient | paramiko.Channel | None]
] = {}


def exec_and_close(
    cli: paramiko.SSHClient, command: str, timeout: float | None = None
) -> tuple[bytes, bytes]:
    """Run ``command``, read stdout/stderr fully, then CLOSE the channel.

    Closing is the whole point: a channel that is never closed lingers as a
    half-open session on the remote sshd and counts against its ``MaxSessions``
    limit (default 10). Leaked exec channels accumulate until every new
    ``open_channel`` — including the interactive terminal's ``invoke_shell`` —
    fails with ``ChannelException(2, 'Connect failed')``.
    """
    _, stdout, stderr = cli.exec_command(command)
    try:
        if timeout is not None:
            try:
                stdout.channel.settimeout(timeout)
            except Exception:
                pass
        out = stdout.read()
        err = stderr.read()
        return out, err
    finally:
        try:
            stdout.channel.close()
        except Exception:
            pass


def exec_and_close_status(
    cli: paramiko.SSHClient, command: str, timeout: float | None = None
) -> tuple[bytes, bytes, int]:
    """Like ``exec_and_close`` but also return the command's exit status.

    The status is read with ``channel.recv_exit_status()`` AFTER stdout/stderr are
    fully drained, so the command has already finished and the call returns
    immediately (no extra round-trip). On any error reading the status (e.g. a
    test fake without the method) we fall back to ``-1`` rather than raising, so
    the caller always gets a usable exit code.
    """
    _, stdout, stderr = cli.exec_command(command)
    try:
        if timeout is not None:
            try:
                stdout.channel.settimeout(timeout)
            except Exception:
                pass
        out = stdout.read()
        err = stderr.read()
        try:
            code = int(stdout.channel.recv_exit_status())
        except Exception:
            code = -1
        return out, err, code
    finally:
        try:
            stdout.channel.close()
        except Exception:
            pass


def write_vm_id_marker(cli: paramiko.SSHClient, vm_id: str) -> None:
    """Best-effort: stamp ``vm_id`` into the guest at ``VM_ID_MARKER_PATH``.

    Written on EVERY boot to the CURRENT vm_id, so a duplicated disk (which carries
    the source's stamp) is corrected as soon as the clone boots. Never raises — a
    VM that can't be stamped just stays 'legacy' and is treated tolerantly on read.
    """
    if not vm_id:
        return
    try:
        cmd = f"printf %s {shlex.quote(str(vm_id))} > {VM_ID_MARKER_PATH}"
        _ = exec_and_close(cli, cmd, timeout=5)
    except Exception as e:
        print("Could not write vm-id marker:", e)


def read_vm_id_marker(cli: paramiko.SSHClient) -> str | None:
    """Read the guest's stamped vm_id, or ``None`` if absent/unreadable (tolerant)."""
    try:
        out, _ = exec_and_close(cli, f"cat {VM_ID_MARKER_PATH} 2>/dev/null", timeout=5)
        marker = out.decode(errors="ignore").strip()
        return marker or None
    except Exception:
        return None


def assert_vm_identity(cli: paramiko.SSHClient, expected_vm_id: str | None) -> None:
    """
    Verify the VM reachable over ``cli`` is ``expected_vm_id``; raise otherwise.

    TOLERANT by design so it deploys without disrupting VMs booted before the marker
    existed: a MISSING marker (legacy VM, or transiently unreadable) is accepted.
    Only a marker that is PRESENT and DIFFERENT — i.e. a real cross-wiring where
    operating would touch the wrong machine — raises :class:`VMIdentityMismatch`.
    """
    if not expected_vm_id:
        return
    marker = read_vm_id_marker(cli)
    if marker is not None and marker != str(expected_vm_id):
        raise VMIdentityMismatch(
            f"VM identity mismatch: expected {expected_vm_id}, port hosts {marker}"
        )


def clear_cache(vm_id: str):
    cache_data[vm_id] = {}


def clear_all_cache():
    global cache_data
    cache_data = {}


def finalize_and_cache(container_id: str, cli: paramiko.SSHClient):
    """
    Take an already-connected SSH client, tune it, open the sftp/shell channels
    and store the full entry in ``cache_data``.

    This is the single place where a cache entry is built, so every code path
    (lazy generation and the boot-time warmup in ``wait_ssh``) produces an
    identical, consistent entry (cli + sftp + chan + transport tuning).
    """
    # Disable Nagle on the SSH transport: tiny keystroke packets must not wait to be
    # coalesced (~40ms otherwise). Keepalive avoids idle drops. Guarded so test fakes
    # without a real transport are a no-op.
    try:
        transport = cli.get_transport()
        if transport is not None:
            try:
                transport.set_keepalive(30)
            except Exception:
                pass
            tsock = getattr(transport, "sock", None)
            if tsock is not None:
                tsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception as e:
        print("Could not enable TCP_NODELAY on SSH transport:", e)

    sftp = cli.open_sftp()

    chan = cli.invoke_shell(width=120, height=32)
    chan.settimeout(0.0)

    cache_data[container_id] = {"cli": cli, "sftp": sftp, "chan": chan}

    return cli, sftp, chan


def _connect(ssh_port: int | None, ssh_user: str | None) -> paramiko.SSHClient:
    """Open and TCP-tune a fresh SSH connection (no caching, no channels)."""
    # Use the shared multi-format loader (Ed25519/RSA/ECDSA) instead of hardcoding
    # Ed25519Key: prod's VM_SSH_PRIVKEY is not necessarily an ed25519 key, and a
    # hardcoded Ed25519Key.from_private_key_file raises SSHException("Invalid key")
    # for RSA/ECDSA keys. wait_ssh already loads the key via load_pkey, so the pool
    # and the interactive console must do the same to stay consistent.
    key = load_pkey(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(
        "127.0.0.1",
        port=ssh_port or 22,
        username=ssh_user or "root",
        pkey=key,
        look_for_keys=False,
    )
    try:
        transport = cli.get_transport()
        if transport is not None:
            try:
                transport.set_keepalive(30)
            except Exception:
                pass
            tsock = getattr(transport, "sock", None)
            if tsock is not None:
                tsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception as e:
        print("Could not tune SSH transport:", e)
    return cli


def _generate_ssh_and_sftp_by_id(
    container_id: str,
    ssh_port: int | None,
    ssh_user: str | None,
):
    print("Generating cache for: ", container_id)
    cli = _connect(ssh_port, ssh_user)
    return finalize_and_cache(container_id, cli)


def _generate_ssh_and_sftp(container: VMRecord):
    return _generate_ssh_and_sftp_by_id(
        container.id, container.ssh_port, container.ssh_user
    )


def cache_ssh_and_sftp_by_id(
    container_id: str,
    ssh_port: int | None,
    ssh_user: str | None,
):
    if container_id not in cache_data:
        _ = _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    data = cache_data[container_id]
    if "cli" not in data:
        _ = _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]
    if "sftp" not in data:
        _ = _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    if data["cli"] is None or data["sftp"] is None:
        _ = _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    # Liveness check via the transport state instead of running a remote command.
    # The old `exec_command("echo hello")` cost a full SSH round-trip on every
    # cached access (every file read/list/search/exec) and leaked the channel it
    # opened (its streams were never read or closed). is_active() is local + cheap.
    cli = cast(paramiko.SSHClient, data["cli"])
    transport = None
    try:
        transport = cli.get_transport()
    except Exception as e:
        print("Exception caching: ", e)
    if transport is None or not transport.is_active():
        _ = _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    return data


def cache_ssh_and_sftp(container: VMRecord):
    return cache_ssh_and_sftp_by_id(
        container.id, container.ssh_port, container.ssh_user
    )


def open_ssh(container: VMRecord):
    val = cache_ssh_and_sftp(container)
    return cast(paramiko.SSHClient, val["cli"])


def open_sftp(container: VMRecord):
    val = cache_ssh_and_sftp(container)
    return cast(paramiko.SFTPClient, val["sftp"])


def open_ssh_and_sftp(container: VMRecord):
    val = cache_ssh_and_sftp(container)
    sftp = cast(paramiko.SFTPClient, val["sftp"])
    cli = cast(paramiko.SSHClient, val["cli"])
    return sftp, cli


def generate_console(container: VMRecord):
    """Open a DEDICATED SSH connection for the interactive terminal.

    The terminal must NOT share the cached connection used by the AI/editor file
    & exec operations. A burst of agent tool calls churns channels on that shared
    connection and can exhaust the VM sshd's ``MaxSessions``; once that happens
    every new ``open_channel`` fails with ``ChannelException(2, 'Connect failed')``
    — including the terminal's ``invoke_shell`` (which is exactly how the terminal
    died under AI load). Its own connection gives the terminal an independent
    session budget, so heavy AI activity can never knock it offline.
    """
    cli = _connect(container.ssh_port, container.ssh_user)

    # Never open a terminal onto the wrong VM: if the port hosts a different vm_id
    # (collision), refuse instead of handing the user someone else's machine.
    try:
        assert_vm_identity(cli, container.id)
    except Exception:
        try:
            cli.close()
        except Exception:
            pass
        raise

    chan = cli.invoke_shell(width=120, height=32)
    # Small timeout (not 0.0): recv() blocks until data arrives (zero added latency)
    # and only wakes periodically to honor shutdown, instead of busy-polling.
    chan.settimeout(0.2)

    return cli, chan
