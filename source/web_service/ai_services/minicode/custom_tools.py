"""Custom tools — per-VM, user/agent-defined tools (the safe extensibility tier).

A custom tool is a directory ``/app/.pequenin/tools/<name>/`` with a ``tool.json``
manifest::

    {
      "name": "run-linter",
      "description": "Run ruff on a path and return findings. Use before committing.",
      "parameters": {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]},
      "command": "python3 run.py"
    }

The agent calls it like any tool. Its validated arguments are delivered as a JSON
object on STDIN (base64 on the wire → no shell-quoting/injection), and ``command``
runs INSIDE the user's VM, in the tool's own directory, via ``execute_sh`` — the SAME
sandbox ``bash`` already runs in. So a custom tool grants NO capability beyond what
``bash`` could already do; it is just a named, schema'd wrapper. Foreground, ~25s cap
(for long work the tool's own command should background it, like bash does).

Discovery runs ONCE per turn (cached on ``Config.custom_tools``), mirroring
``skills.py`` / ``mcp.py``. A bad manifest is skipped; it never breaks the turn.
"""

from __future__ import annotations

import base64
import json
import logging
import posixpath
import re
import shlex

from vm_manager.vm_client import VMPaths

from .tools.base import Tool, truncate

logger = logging.getLogger(__name__)

CUSTOM_TOOLS_DIR = "/app/.pequenin/tools"
# Same naming rule as skills: lowercase alphanumerics joined by single hyphens, and
# it must equal the folder name. Also a valid OpenAI tool name.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_NAME_CHARS = 64
_MAX_DESC_CHARS = 1024


def _read(client, cid: str, path: str) -> str | None:
    try:
        resp = client.read_file(cid, path)
    except Exception:
        return None
    if isinstance(resp, dict) and resp.get("found"):
        return resp.get("content") or ""
    return None


def _normalize_schema(schema: object) -> dict:
    """Coerce a manifest ``parameters`` into an OpenAI-style object schema."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out = dict(schema)
    out["type"] = "object"
    if not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


class CustomTool(Tool):
    """A VM-side command exposed to the model as a normal minicode tool.

    ``execute`` runs ``command`` in the tool's directory inside the VM, feeding the
    validated args as a JSON object on stdin, and returns the combined stdout/stderr.
    """

    read_only = False

    def __init__(self, name, description, parameters, command, base_dir):
        self.name = name
        self.description = (description or f"Custom tool '{name}'.")[:_MAX_DESC_CHARS]
        self.parameters = parameters
        self._command = command
        self._base_dir = base_dir

    def execute(self, args: dict, ctx) -> str:
        from .tools import vm

        client, cid = vm.get_client(ctx)
        payload = json.dumps(args or {})
        b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        # cd into the tool's dir, decode the args and pipe them to the command's stdin.
        # `&&` binds looser than `|`, so cd applies to the whole pipeline.
        cmd = (
            f"cd {shlex.quote(self._base_dir)} && "
            f"printf '%s' {shlex.quote(b64)} | base64 -d | {self._command}"
        )
        timeout = int(getattr(ctx.config, "foreground_timeout", 25) or 25)
        resp = client.execute_sh(cid, cmd, timeout=timeout)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "command failed or timed out"
            vm.audit(
                "exec_command",
                cid,
                "Custom tool",
                {"tool": self.name},
                success=False,
            )
            return (
                f"Error: custom tool '{self.name}' failed: {reason}. "
                f"(Custom tools run foreground, ~{timeout}s; background long work inside the command.)"
            )
        out = (str(resp.get("stdout") or "")) + (str(resp.get("stderr") or ""))
        vm.audit("exec_command", cid, "Custom tool", {"tool": self.name})
        return truncate(out, from_tail=True) or "(no output)"


def discover_custom_tools(config) -> list[CustomTool]:
    """Read ``/app/.pequenin/tools/<name>/tool.json`` from the VM (once per turn) and
    build a ``CustomTool`` for each valid manifest. Best-effort: invalid manifests are
    skipped, a VM error yields ``[]`` — never raises."""
    from .tools.vm import client_for_config

    client, cid = client_for_config(config)
    if client is None:
        return []
    try:
        entries = client.list_dirs(cid, VMPaths(paths=[CUSTOM_TOOLS_DIR], depth=2))
    except Exception:
        return []
    if not isinstance(entries, list):
        return []

    tools: dict[str, CustomTool] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("name") != "tool.json" or e.get("path_type") != "file":
            continue
        path = str(e.get("path") or "")
        if not path:
            continue
        base_dir = posixpath.dirname(path)
        folder = posixpath.basename(base_dir)
        content = _read(client, cid, path)
        if content is None:
            continue
        try:
            man = json.loads(content)
        except Exception:
            logger.warning("%s/tool.json is not valid JSON; skipped", folder)
            continue
        if not isinstance(man, dict):
            continue
        name = str(man.get("name") or "").strip()
        desc = " ".join(str(man.get("description") or "").split())
        command = str(man.get("command") or "").strip()
        if not name or not _NAME_RE.match(name) or len(name) > _MAX_NAME_CHARS:
            logger.warning("%s: invalid/missing name; skipped", folder)
            continue
        if name != folder:
            logger.warning("%s: name '%s' != folder; skipped", folder, name)
            continue
        if not desc or not command:
            logger.warning("%s: missing description or command; skipped", name)
            continue
        tools[name] = CustomTool(
            name, desc, _normalize_schema(man.get("parameters")), command, base_dir
        )
    return sorted(tools.values(), key=lambda t: t.name)
