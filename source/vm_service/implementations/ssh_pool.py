"""Per-VM pool of reusable SSH connections for file/exec operations.

Two SSH "lanes" coexist per VM:

- The interactive **terminal** keeps its OWN dedicated connection
  (``ssh_cache.generate_console``) for the whole session.
- Every other operation — the AI agent's read/grep/edit/exec, the editor's file
  ops, background-process control — **borrows** a connection from this bounded
  per-VM pool, uses it EXCLUSIVELY for the duration of one operation, and returns
  it. A borrowed connection carries its own SFTP client, so concurrent operations
  (e.g. the agent grepping while the editor reads a file) never race the same
  SFTP client and never serialize behind a single lock. The pool is capped per VM
  (``_POOL_SIZE``), so the VM sshd's ``MaxSessions`` can't be exhausted — and exec
  channels are still closed promptly by ``exec_and_close``.

The pool lives in-process (vm_service is a single process); connections are real
paramiko TCP sockets and cannot be shared across processes or stored in Redis.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .ssh_cache import _connect, assert_vm_identity

# Max concurrent borrowed connections per VM. Each is independent (own channels +
# own SFTP), so this bounds channels-per-VM well under the sshd MaxSessions while
# still allowing the agent and the editor to work the same VM in parallel.
_POOL_SIZE = 4

_idle: dict[str, list["_Conn"]] = {}
_sems: dict[str, threading.BoundedSemaphore] = {}
_guard = threading.Lock()


class _Conn:
    __slots__ = ("cli", "sftp")

    def __init__(self, cli: Any, sftp: Any) -> None:
        self.cli = cli
        self.sftp = sftp


def _sem(vm_id: str) -> threading.BoundedSemaphore:
    with _guard:
        s = _sems.get(vm_id)
        if s is None:
            s = threading.BoundedSemaphore(_POOL_SIZE)
            _sems[vm_id] = s
        return s


def _alive(conn: "_Conn") -> bool:
    try:
        t = conn.cli.get_transport()
        return t is not None and t.is_active()
    except Exception:
        return False


def _close(conn: "_Conn") -> None:
    for obj in (getattr(conn, "sftp", None), getattr(conn, "cli", None)):
        try:
            if obj is not None:
                obj.close()
        except Exception:
            pass


@contextmanager
def borrow(container: Any) -> Iterator["_Conn"]:
    """Borrow an SSH connection (cli + sftp) for one VM operation.

    Blocks if all ``_POOL_SIZE`` connections for this VM are in use. A healthy
    connection is returned to the pool on success; a connection whose operation
    raised (or that died) is closed and dropped so it never poisons the pool.
    """
    vm_id = container.id
    sem = _sem(vm_id)
    sem.acquire()
    conn: "_Conn | None" = None
    failed = False
    try:
        with _guard:
            idle = _idle.get(vm_id)
            conn = idle.pop() if idle else None
        if conn is not None and not _alive(conn):
            _close(conn)
            conn = None
        if conn is None:
            cli = _connect(container.ssh_port, container.ssh_user)
            conn = _Conn(cli, cli.open_sftp())
            # Fresh connection: confirm the port really hosts THIS vm before use.
            # A mismatch raises; the finally below closes the connection so it never
            # enters the pool and no file/exec op ever lands on the wrong VM.
            assert_vm_identity(conn.cli, getattr(container, "id", None))
        yield conn
    except Exception:
        failed = True
        raise
    finally:
        if conn is not None and not failed and _alive(conn):
            with _guard:
                _idle.setdefault(vm_id, []).append(conn)
        elif conn is not None:
            _close(conn)
        sem.release()


def drop_pool(vm_id: str) -> None:
    """Close and forget all idle connections for a VM (e.g. when it stops)."""
    with _guard:
        idle = _idle.pop(vm_id, [])
        _sems.pop(vm_id, None)
    for conn in idle:
        _close(conn)
