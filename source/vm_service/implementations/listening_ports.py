"""Autodetect TCP ports an app is listening on inside a VM.

Used by the IDE preview to suggest which port to proxy. We run ``ss`` over a
pooled SSH connection (``borrow``) and parse its output. Every detected port is
reachable by the preview proxy — even loopback-only ones — because the
``direct-tcpip`` channel is opened *inside* the guest, so ``127.0.0.1`` from the
guest's point of view is the app itself.
"""

from __future__ import annotations

import re

from models import VMRecord, ListeningPort
from .ssh_cache import exec_and_close
from .ssh_pool import borrow

# Ports we never surface as preview targets: SSH (the VM's only externally
# forwarded port — offering it is useless and a way to point the SSRF-guarded
# proxy at sshd) plus default system daemons that listen out of the box (DNS
# stub :53, mDNS :5353, LLMNR :5355) and are pure noise in the selector.
_HIDDEN_PORTS: frozenset[int] = frozenset({22, 53, 5353, 5355})

# Processes whose sockets are infrastructure, not the user's app. Names come from
# `ss -p`; systemd-resolved is reported (truncated) as "systemd-resolve".
_HIDDEN_PROCESSES: frozenset[str] = frozenset(
    {
        "systemd-resolve",
        "systemd-resolved",
        "sshd",
        "chronyd",
        "avahi-daemon",
        "cupsd",
        "rpcbind",
    }
)

# `ss -p` renders process owners as: users:(("node",pid=1234,fd=20),("node",pid=...)).
# Grab the first ("name",pid=N) pair; that is enough to label the selector.
_PROC_RE = re.compile(r'\("([^"]+)",pid=(\d+)')

# `ss -ltnpH`: -l listening, -t tcp, -n numeric (no DNS), -p process (needs root;
# VMs run as root), -H no header. The `|| ss -ltnH` fallback keeps the ports even
# if a build ever lacks process introspection.
_SS_CMD = "ss -ltnpH 2>/dev/null || ss -ltnH"


def _parse_ss(text: str) -> list[ListeningPort]:
    """Parse ``ss -ltnpH`` output into a deduped, port-sorted list."""
    by_port: dict[int, ListeningPort] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        # State Recv-Q Send-Q Local:Port Peer:Port [users:(...)]
        if len(fields) < 4:
            continue

        local = fields[3]
        addr, sep, port_str = local.rpartition(":")
        if not sep:
            continue
        try:
            port = int(port_str)
        except ValueError:
            continue

        addr = addr.strip("[]")  # IPv6 comes bracketed: [::]:8000 -> ::

        process: str | None = None
        pid: int | None = None
        if len(fields) >= 6:
            m = _PROC_RE.search(" ".join(fields[5:]))
            if m:
                process = m.group(1)
                pid = int(m.group(2))

        # Drop SSH/system ports and known infrastructure daemons (e.g.
        # systemd-resolved on :53/:5355) so the selector only shows app ports.
        if port in _HIDDEN_PORTS or (
            process is not None and process in _HIDDEN_PROCESSES
        ):
            continue

        existing = by_port.get(port)
        if existing is None:
            by_port[port] = ListeningPort(
                port=port, address=addr, process=process, pid=pid
            )
            continue

        # Same port seen twice (typically once on 0.0.0.0 and once on [::]).
        # Keep one entry: learn the process if we didn't have it, and prefer a
        # wildcard bind label over a loopback one for display.
        if existing.process is None and process is not None:
            existing.process = process
            existing.pid = pid
        if existing.address in ("127.0.0.1", "::1") and addr in ("0.0.0.0", "::", "*"):
            existing.address = addr

    return sorted(by_port.values(), key=lambda p: p.port)


def listening_ports(container: VMRecord) -> list[ListeningPort]:
    """Return the TCP ports an app is listening on inside ``container``."""
    with borrow(container) as conn:
        out, _ = exec_and_close(conn.cli, _SS_CMD)
    return _parse_ss(out.decode("utf-8", errors="replace"))
