import os
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from qemu_manager import ssh_peer


@pytest.mark.parametrize(
    ("process_matches", "connection_matches"),
    [(True, True), (False, True), (True, False)],
)
def test_verify_ssh_peer_checks_pidfile_and_connected_socket(
    tmp_path, monkeypatch, process_matches, connection_matches
):
    pidfile = tmp_path / "qemu.pid"
    pidfile.write_text("42", encoding="ascii")
    socket_peer = Mock()
    socket_peer.getpeername.return_value = ("127.0.0.1", 2222)
    socket_peer.getsockname.return_value = ("127.0.0.1", 3333)

    process = Mock()
    process.cmdline.return_value = [
        "qemu-system-x86_64",
        "-pidfile",
        str(pidfile if process_matches else tmp_path / "different-qemu.pid"),
    ]
    process.uids.return_value = SimpleNamespace(effective=os.geteuid())
    process.is_running.return_value = True
    process.net_connections.return_value = [
        SimpleNamespace(
            status=psutil.CONN_ESTABLISHED,
            laddr=("127.0.0.1", 2222),
            raddr=("127.0.0.1", 3333 if connection_matches else 3334),
        )
    ]
    monkeypatch.setattr(ssh_peer.psutil, "Process", lambda pid: process)

    if process_matches and connection_matches:
        ssh_peer.verify_ssh_peer(socket_peer, str(pidfile))
    else:
        with pytest.raises(ssh_peer.VMIdentityMismatch):
            ssh_peer.verify_ssh_peer(socket_peer, str(pidfile))
