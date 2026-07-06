"""FastMCP server exposing 10 platform tools over the public /api/v1 surface.

Task-shaped tools (not a CRUD mirror): few, well-described, output-truncated. The
API key is taken from the MCP client's Authorization header when present, else
from PEQUEROKU_API_KEY — so per-user keys flow through and scopes are honored.

The server also ships ``instructions`` (see ``prompts.py``): global context handed
to the client on connect so the agent knows what a VM is, that types must be
discovered with ``list_types``, and how the tools fit together.
"""

from __future__ import annotations

import functools
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from . import config, prompts
from .client import PlatformClient, PlatformError
from .prompts import SERVER_INSTRUCTIONS

mcp = FastMCP(
    "pequeroku",
    host=config.HOST,
    port=config.PORT,
    instructions=SERVER_INSTRUCTIONS,
)


# --- helpers ---------------------------------------------------------------


def _resolve_api_key(ctx: Context | None) -> str:
    """Prefer the caller's bearer token; fall back to the configured shared key.

    With no token and no ``config.API_KEY`` this returns "", which makes
    ``_client`` raise ``unauthorized`` (a 401 at the edge) — so a bare deployment
    is closed by default, never an open relay.
    """
    if ctx is not None:
        try:
            request = ctx.request_context.request  # Starlette request on HTTP
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1].strip()
                if token:
                    return token
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
def list_types(ctx: Context = None) -> str:
    """List the VM flavors your API key may use, with specs and credit cost.

    Call this before creating anything: it returns each allowed type's `id`,
    `name`, `vcpus`, `memory_mb`, `disk_gib` and `credits_cost`. The `name` (or
    `id`) is what you pass as `type` to `run_code` / `get_or_create_container`.
    """
    return _dump(_client(ctx).list_types())


@mcp.tool()
@_guard
def run_code(
    command: str,
    files: list[dict] | None = None,
    type: str | None = None,
    timeout_seconds: int = 120,
    ctx: Context = None,
) -> str:
    """Run a command in a fresh throwaway Debian VM and return its output.

    Best for one-shots: PequeRoku boots the VM, writes `files` ([{path, content}])
    into `/app` (the working directory), runs `command`, returns
    stdout/stderr/exit_code, and destroys the VM. No state survives — use a
    persistent container (`get_or_create_container`) if you need it to.

    `type` is a flavor name or id from `list_types`; omit it for the cheapest
    allowed type. `timeout_seconds` is a hard cap (max 600).
    """
    result = _client(ctx).run_code(
        command, files=files, type=type, timeout_seconds=timeout_seconds
    )
    return _dump(result)


@mcp.tool()
@_guard
def list_containers(ctx: Context = None) -> str:
    """List your persistent containers with their status, flavor and specs."""
    return _dump(_client(ctx).list_containers())


@mcp.tool()
@_guard
def get_or_create_container(
    name: str, type: str | None = None, ctx: Context = None
) -> str:
    """Return the container named `name`, creating it (needs `type`) if absent.

    Idempotent way to get a stable Debian workspace (working dir `/app`, files
    persist across reboots) to come back to across calls. `type` is a flavor name
    or id from `list_types`; it is required only when the container must be
    created. Returns its `id`, used by the other container tools.
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
    """Run a shell command in an existing container (Debian).

    Each call runs in a fresh shell with no retained cwd or shell state, so
    `cd /app && ...` if you depend on the working directory. `background=true`
    starts a detached process and returns a process_id you poll with
    process_status — use it for servers or long jobs, and bind apps to 0.0.0.0
    so get_preview can reach them.
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
    """Write a batch of files into a container. `files` is [{path, content}].

    Relative paths resolve under `/app`, the working directory. Use this to seed
    or update a workspace, then drive it with `container_exec`.
    """
    return _dump(_client(ctx).write_files(container_id, files))


@mcp.tool()
@_guard
def read_path(container_id: int, path: str, ctx: Context = None) -> str:
    """Read a path: file → its contents; directory → its listing.

    Project files live under `/app`. File contents are truncated past the output
    limit (a `truncated` flag marks it).
    """
    return _dump(_client(ctx).read_path(container_id, path))


@mcp.tool()
@_guard
def get_preview(
    container_id: int, port: int | None = None, path: str = "/", ctx: Context = None
) -> str:
    """Inspect or fetch a web app running inside the container.

    - No `port`: list the ports an app is listening on. Each entry includes a
      ready-to-use absolute `preview_url`. Empty until your app is actually
      listening — start it (e.g. `container_exec(..., background=true)`) bound to
      0.0.0.0 on a high port first.
    - With `port` (and optional `path`, default `/`): fetch the LIVE response the
      app serves and return its `status`, `content_type` and `body` — so you can
      verify the app end-to-end, not just that a port is open.

    Auth is automatic: the preview is reached with your own API key. To hand the
    URL to a human/browser instead, append `?__pk_token=<your key>` to the
    `preview_url` (or send `Authorization: Bearer <your key>`); it authenticates
    the same owner-only preview and drops a short-lived cookie so the page's
    assets load too.
    """
    client = _client(ctx)
    if port is None:
        return _dump(client.get_preview(container_id))
    return _dump(client.fetch_preview(container_id, port, path))


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


# --- prompts ----------------------------------------------------------------
# Reusable, task-shaped starters surfaced to the client (the "Prompts" list in an
# MCP client). Each expands into a user message that bakes in the right PequeRoku
# workflow; the wording lives in prompts.py.


@mcp.prompt(
    description="Run code or a command in a throwaway VM and report the result."
)
def run_in_sandbox(task: str) -> str:
    """One-shot in a fresh VM. `task` is what to run (a command, or code to run)."""
    return prompts.RUN_IN_SANDBOX.format(task=task)


@mcp.prompt(
    description="Build and serve a web app in a persistent container, with a preview."
)
def deploy_web_app(app: str) -> str:
    """Stand up a web app in a persistent container. `app` describes what to deploy."""
    return prompts.DEPLOY_WEB_APP.format(app=app)


@mcp.prompt(
    description="Get or create a named persistent workspace and report its state."
)
def setup_workspace(name: str) -> str:
    """Get/create a persistent workspace by `name` and inspect what's in /app."""
    return prompts.SETUP_WORKSPACE.format(name=name)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
