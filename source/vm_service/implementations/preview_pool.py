"""Dedicated per-VM SSH connection pool for the preview HTTP proxy.

Kept SEPARATE from the file/exec pool (``ssh_pool``) on purpose: a preview page
that pulls many assets opens a burst of ``direct-tcpip`` channels, and routing
those through the agent/editor pool would starve it (and vice versa). Each
borrowed connection is used to open ONE short-lived port-forward channel per
HTTP request and is then returned. ``direct-tcpip`` channels are forwarding
channels, so they do not count against the guest sshd's ``MaxSessions``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .ssh_cache import _connect

# Browsers open ~6 connections per origin; size the lane to match so a page's
# assets proxy concurrently without queueing behind one another.
_POOL_SIZE = 6

_idle: dict[str, list[Any]] = {}
_sems: dict[str, threading.BoundedSemaphore] = {}
_guard = threading.Lock()


def _sem(vm_id: str) -> threading.BoundedSemaphore:
    with _guard:
        s = _sems.get(vm_id)
        if s is None:
            s = threading.BoundedSemaphore(_POOL_SIZE)
            _sems[vm_id] = s
        return s


def _alive(cli: Any) -> bool:
    try:
        t = cli.get_transport()
        return t is not None and t.is_active()
    except Exception:
        return False


def _close(cli: Any) -> None:
    try:
        cli.close()
    except Exception:
        pass


@contextmanager
def borrow_preview(container: Any) -> Iterator[Any]:
    """Borrow an SSH client for one preview request (open a direct-tcpip channel on it).

    Blocks if all ``_POOL_SIZE`` connections for this VM are in use. A healthy
    connection returns to the pool; a dead/failed one is dropped so it never
    poisons the pool.
    """
    vm_id = container.id
    sem = _sem(vm_id)
    sem.acquire()
    cli: Any = None
    failed = False
    try:
        with _guard:
            idle = _idle.get(vm_id)
            cli = idle.pop() if idle else None
        if cli is not None and not _alive(cli):
            _close(cli)
            cli = None
        if cli is None:
            cli = _connect(container.ssh_port, container.ssh_user)
        yield cli
    except Exception:
        failed = True
        raise
    finally:
        if cli is not None and not failed and _alive(cli):
            with _guard:
                _idle.setdefault(vm_id, []).append(cli)
        elif cli is not None:
            _close(cli)
        sem.release()


def drop_preview_pool(vm_id: str) -> None:
    """Close and forget all idle preview connections for a VM (e.g. when it stops)."""
    with _guard:
        idle = _idle.pop(vm_id, [])
        _sems.pop(vm_id, None)
    for cli in idle:
        _close(cli)
