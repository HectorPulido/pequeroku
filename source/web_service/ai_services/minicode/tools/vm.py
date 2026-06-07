"""Bridge between minicode's tools and Pequeroku's remote VM.

minicode's tools are written for a local filesystem; in Pequeroku that
"filesystem" lives in the user's VM and is accessed over HTTP→SSH via
``VMServiceClient``. This module centralizes what is common to all VM-backed tools:

- get the ``VMServiceClient`` client from the Config's ``container`` (cached to
  reuse the connection pool across calls within the same turn),
- resolve relative paths against the workdir (``/app``) in POSIX format (the VM is
  Debian, not the Django server's OS),
- audit each action (best-effort; never brings the tool down).

Everything runs inside the worker thread started by ``frontends.pipeline`` (via
``asyncio.to_thread``), so the synchronous calls (HTTP, audit ORM) are safe and do
not block the Channels event loop.
"""

from __future__ import annotations

import posixpath
from typing import Any

from vm_manager.vm_client import VMServiceClient
from internal_config.audit import audit_agent_tool


class VMUnavailable(Exception):
    """There is no ``container`` associated with the Config (session badly initialized)."""


def client_for_config(config: Any) -> tuple[VMServiceClient | None, str | None]:
    """``(client, container_id)`` for the VM bound to a ``Config``.

    Returns ``(None, None)`` if the Config has no container (instead of raising), so
    the best-effort loaders (``project.py`` / ``skills.py``, which run once per turn)
    can degrade to "no context" without breaking the turn. The client is cached on
    ``config._vm_client`` to reuse the connection pool.
    """
    container = getattr(config, "container", None)
    if container is None:
        return None, None
    client = getattr(config, "_vm_client", None)
    if client is None:
        client = VMServiceClient(container.node)
        try:
            config._vm_client = client
        except Exception:
            pass
    return client, str(container.container_id)


def get_client(ctx: Any) -> tuple[VMServiceClient, str]:
    """Return ``(client, container_id)`` for the VM bound to this session.

    Tool variant: it requires a container (raises ``VMUnavailable`` if missing).
    """
    client, cid = client_for_config(ctx.config)
    if client is None or cid is None:
        raise VMUnavailable("No container bound to this agent session.")
    return client, cid


def resolve(ctx: Any, path: str | None) -> str:
    """Resolve ``path`` against the workdir (``/app``) as an absolute POSIX path."""
    workdir = getattr(ctx.config, "workdir", "/app") or "/app"
    p = (path or "").strip()
    if not p:
        return workdir
    if not p.startswith("/"):
        p = posixpath.join(workdir, p)
    return posixpath.normpath(p)


def relpath(path: str, root: str) -> str:
    """``path`` relative to ``root`` (for display / glob matching)."""
    try:
        return posixpath.relpath(path, root)
    except Exception:
        return path


def audit(
    action: str,
    target_id: str,
    message: str,
    metadata: dict[str, object] | None = None,
    success: bool = True,
) -> None:
    """Record an audit entry (best-effort)."""
    try:
        audit_agent_tool(
            action=f"agent_tool.{action}",
            target_type="container",
            target_id=target_id,
            message=message,
            metadata=metadata or {},
            success=success,
        )
    except Exception:
        pass
