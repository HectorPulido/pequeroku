"""Puente de las tools de minicode con la VM remota de Pequeroku.

Las tools de minicode están escritas para un filesystem local; en Pequeroku ese
"filesystem" vive en la VM del usuario y se accede por HTTP→SSH vía
``VMServiceClient``. Este módulo centraliza lo común para todas las tools VM-backed:

- obtener el cliente del ``VMServiceClient`` a partir del ``container`` del Config
  (cacheado para reusar la connection pool entre llamadas del mismo turno),
- resolver rutas relativas contra el workdir (``/app``) en formato POSIX (la VM es
  Debian, no el SO del servidor de Django),
- auditar cada acción (best-effort; nunca tumba la tool).

Todo corre dentro del hilo worker que arranca ``frontends.pipeline`` (vía
``asyncio.to_thread``), así que las llamadas síncronas (HTTP, ORM de auditoría)
son seguras y no bloquean el event loop de Channels.
"""
from __future__ import annotations

import posixpath
from typing import Any

from vm_manager.vm_client import VMServiceClient
from internal_config.audit import audit_agent_tool


class VMUnavailable(Exception):
    """No hay un ``container`` asociado al Config (sesión mal inicializada)."""


def get_client(ctx: Any) -> tuple[VMServiceClient, str]:
    """Devuelve ``(client, container_id)`` para la VM ligada a esta sesión."""
    container = getattr(ctx.config, "container", None)
    if container is None:
        raise VMUnavailable("No container bound to this agent session.")
    client = getattr(ctx.config, "_vm_client", None)
    if client is None:
        client = VMServiceClient(container.node)
        try:
            ctx.config._vm_client = client
        except Exception:
            pass
    return client, str(container.container_id)


def resolve(ctx: Any, path: str | None) -> str:
    """Resuelve ``path`` contra el workdir (``/app``) como ruta POSIX absoluta."""
    workdir = getattr(ctx.config, "workdir", "/app") or "/app"
    p = (path or "").strip()
    if not p:
        return workdir
    if not p.startswith("/"):
        p = posixpath.join(workdir, p)
    return posixpath.normpath(p)


def relpath(path: str, root: str) -> str:
    """Ruta de ``path`` relativa a ``root`` (para mostrar / hacer match de globs)."""
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
    """Registra una entrada de auditoría (best-effort)."""
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
