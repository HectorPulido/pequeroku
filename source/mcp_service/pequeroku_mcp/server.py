"""FastMCP server exposing 9 platform tools over the public /api/v1 surface.

Task-shaped tools (not a CRUD mirror): few, well-described, output-truncated. The
API key is taken from the MCP client's Authorization header when present, else
from PEQUEROKU_API_KEY — so per-user keys flow through and scopes are honored.
"""

from __future__ import annotations

import functools
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from . import config
from .client import PlatformClient, PlatformError

mcp = FastMCP("pequeroku", host=config.HOST, port=config.PORT)


# --- helpers ---------------------------------------------------------------


def _resolve_api_key(ctx: Context | None) -> str:
    """Prefer the caller's bearer token; fall back to the configured key."""
    if ctx is not None:
        try:
            request = ctx.request_context.request  # Starlette request on HTTP
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth.split(" ", 1)[1].strip()
        except Exception:
            pass
    return config.API_KEY


def _client(ctx: Context | None) -> PlatformClient:
    api_key = _resolve_api_key(ctx)
    if not api_key:
        raise PlatformError(
            "unauthorized",
            "No API key. Set Authorization: Bearer pk_... in the MCP client config.",
        )
    return PlatformClient(config.API_URL, api_key)


def _truncate(text: str) -> str:
    data = text.encode("utf-8")
    if len(data) <= config.OUTPUT_LIMIT:
        return text
    clipped = data[: config.OUTPUT_LIMIT].decode("utf-8", errors="ignore")
    return clipped + "\n…[truncated]"


def _dump(value: Any) -> str:
    return _truncate(json.dumps(value, indent=2, default=str))


def _guard(fn):
    """Turn PlatformError into actionable text instead of a stack trace.

    Uses ``functools.wraps`` so FastMCP still sees the wrapped function's real
    signature/annotations (it derives the tool's input schema from them); a bare
    ``*args, **kwargs`` wrapper would expose ``args``/``kwargs`` as the schema.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PlatformError as e:
            hint = ""
            if e.code == "quota_exceeded":
                hint = " (destroy a container or use run_code with a cheaper type)"
            elif e.code == "forbidden_scope":
                hint = " (this API key lacks the required scope)"
            return f"Error ({e.code}): {e.message}{hint}"

    return wrapper


# --- tools -----------------------------------------------------------------


@mcp.tool()
@_guard
def run_code(
    command: str,
    files: list[dict] | None = None,
    type: str | None = None,
    timeout_seconds: int = 120,
    ctx: Context = None,
) -> str:
    """Run a command in a fresh throwaway VM and return its output.

    Best for one-shots: PequeRoku creates the VM, optionally writes `files`
    ([{path, content}]), runs `command`, returns stdout/stderr/exit_code, and
    destroys the VM. Use a persistent container instead if you need state to
    survive between calls.
    """
    result = _client(ctx).run_code(
        command, files=files, type=type, timeout_seconds=timeout_seconds
    )
    return _dump(result)


@mcp.tool()
@_guard
def list_containers(ctx: Context = None) -> str:
    """List your persistent containers with their status and flavor."""
    return _dump(_client(ctx).list_containers())


@mcp.tool()
@_guard
def get_or_create_container(
    name: str, type: str | None = None, ctx: Context = None
) -> str:
    """Return the container named `name`, creating it (needs `type`) if absent.

    Idempotent way to get a stable workspace to come back to across calls.
    """
    return _dump(_client(ctx).get_or_create_container(name, type=type))


@mcp.tool()
@_guard
def container_exec(
    container_id: int,
    command: str,
    background: bool = False,
    ctx: Context = None,
) -> str:
    """Run a command in an existing container.

    `background=true` starts a detached process and returns a process_id you can
    poll with process_status (use it for servers or long jobs).
    """
    return _dump(
        _client(ctx).container_exec(container_id, command, background=background)
    )


@mcp.tool()
@_guard
def process_status(container_id: int, process_id: str, ctx: Context = None) -> str:
    """Get the status and recent output of a background process."""
    return _dump(_client(ctx).process_status(container_id, process_id))


@mcp.tool()
@_guard
def write_files(container_id: int, files: list[dict], ctx: Context = None) -> str:
    """Write a batch of files into a container. `files` is [{path, content}]."""
    return _dump(_client(ctx).write_files(container_id, files))


@mcp.tool()
@_guard
def read_path(container_id: int, path: str, ctx: Context = None) -> str:
    """Read a path: file → its contents; directory → its listing."""
    return _dump(_client(ctx).read_path(container_id, path))


@mcp.tool()
@_guard
def get_preview(container_id: int, ctx: Context = None) -> str:
    """List the ports an app is listening on, with preview paths."""
    return _dump(_client(ctx).get_preview(container_id))


@mcp.tool()
@_guard
def destroy_container(
    container_id: int, confirm: bool = False, ctx: Context = None
) -> str:
    """Destroy a container. Requires `confirm=true` — this is irreversible."""
    if not confirm:
        return "Refused: pass confirm=true to destroy this container (irreversible)."
    _client(ctx).destroy_container(container_id)
    return f"Container {container_id} destroyed."


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
