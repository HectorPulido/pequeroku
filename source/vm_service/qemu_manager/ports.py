from typing import cast
import socket
import threading

# Ports handed out by pick_free_port() but not yet released (i.e. a VM is booting
# and about to bind this port). Guards against the TOCTOU where two concurrent
# start_vm calls both bind :0, read the SAME free port, close their probe socket
# and each hand it to a different VM — only one QEMU can then bind it, and the
# other VM's record silently points at the first VM's port (isolation break).
_reserved: set[int] = set()
_reserved_lock = threading.Lock()


def pick_free_port(max_attempts: int = 200) -> int:
    """
    Reserve a free localhost TCP port for a VM's SSH hostfwd.

    Unlike the old implementation, the returned port is recorded in a process-wide
    reservation set so a concurrent ``pick_free_port`` never returns the same
    number while the first VM is still booting. Call :func:`release_port` once QEMU
    has bound the port (or the boot failed) to free the reservation.
    """
    with _reserved_lock:
        for _ in range(max_attempts):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", 0))
                port: int = cast(int, s.getsockname()[1])
            finally:
                s.close()
            if port in _reserved:
                # The OS handed back a port we already promised to another
                # in-flight boot; probe again for a different one.
                continue
            _reserved.add(port)
            print("Port selected", port)
            return port
    raise RuntimeError("could not find a free port after retries")


def release_port(port: int | None) -> None:
    """
    Release a port reservation made by :func:`pick_free_port`.

    Safe to call for a port that was never reserved (idempotent), so callers can
    release unconditionally on both the success and failure paths of a boot.
    """
    if port is None:
        return
    with _reserved_lock:
        _reserved.discard(int(port))
