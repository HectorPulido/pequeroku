"""Verify SSH routing using socket ownership in the QEMU host namespace."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import psutil


class VMIdentityMismatch(Exception):
    """The SSH connection could not be tied to the expected VM's QEMU process."""


def _owns_socket(pid: int, server_port: int, client_port: int) -> bool:
    # Check the accepted socket's full tuple. A listening socket or a port
    # mentioned in the QEMU command line does not identify an existing connection.
    return any(
        conn.status == psutil.CONN_ESTABLISHED
        and conn.laddr == ("127.0.0.1", server_port)
        and conn.raddr == ("127.0.0.1", client_port)
        for conn in psutil.Process(pid).net_connections(kind="tcp4")
    )


def verify_ssh_peer(sock: socket.socket, pidfile: str) -> None:
    try:
        pid = int(Path(pidfile).read_text(encoding="ascii").strip())
        if pid <= 0:
            raise ValueError("Invalid QEMU PID")
        process = psutil.Process(pid)
        command = process.cmdline()
        process_pidfile = command[command.index("-pidfile") + 1]
        if os.path.normpath(process_pidfile) != os.path.normpath(pidfile):
            raise ValueError("QEMU process has a different pidfile")
        server_ip, server_port = sock.getpeername()
        client_ip, client_port = sock.getsockname()
        if (server_ip, client_ip) != ("127.0.0.1", "127.0.0.1"):
            raise ValueError("SSH connection is outside loopback")

        uid = process.uids().effective
        if uid == os.geteuid():
            owns_socket = _owns_socket(pid, server_port, client_port)
        else:
            # Docker root typically lacks CAP_SYS_PTRACE and cannot inspect
            # another UID's procfs file descriptors. Read them as the QEMU user.
            owns_socket = (
                subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        str(pid),
                        str(server_port),
                        str(client_port),
                    ],
                    user=uid,
                    group=process.gids().effective,
                    extra_groups=[],
                    timeout=3,
                    check=False,
                ).returncode
                == 0
            )
        if owns_socket and process.is_running():
            return
    except (OSError, ValueError, IndexError, psutil.Error, subprocess.SubprocessError):
        pass
    raise VMIdentityMismatch("Cannot verify SSH peer for VM")


if __name__ == "__main__":
    try:
        sys.exit(0 if _owns_socket(*map(int, sys.argv[1:])) else 1)
    except psutil.Error:
        sys.exit(1)
