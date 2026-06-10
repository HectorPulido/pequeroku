"""MCP (Model Context Protocol) — REMOTE HTTP servers only (the "easy" v1).

Scope, deliberately bounded (see AI.md): opencode's MCP model assumes a single-user
CLI on the user's own machine; Pequeroku's agent runs on a SHARED, multi-tenant
Django server, per turn, with no persistent session process. So this v1 ports only
the part that maps cleanly:

- REMOTE servers over HTTP (Streamable HTTP / JSON-RPC) ONLY. No local/stdio
  (spawning user-specified processes on the shared host is unsafe; doing it inside
  the VM would need a new vm_service stdio bridge — out of scope).
- Header / API-key auth ONLY. No OAuth (its browser + local-callback flow does not
  map to a hosted multi-tenant web app).
- Servers are declared PER-VM in ``/app/.pequenin/mcp.json`` (persists with the
  workspace, wiped on reset — like AGENTS.md/skills). Read + connected ONCE per turn
  in the pipeline worker thread; each MCP tool is appended to the agent's toolset for
  that turn as a normal minicode ``Tool`` named ``<server>_<tool>``.
- Egress guard: requests leave the SHARED server, so user-controlled URLs are an
  SSRF risk; private/loopback/link-local hosts are blocked unless
  ``PEQUENIN_MCP_ALLOW_PRIVATE`` is set.

Everything is SYNC (``requests``), matching minicode's worker-thread model — no async
bridge, no new dependency.

mcp.json schema (opencode-compatible subset)::

    {
      "mcp": {
        "context7": {
          "type": "remote",
          "url": "https://mcp.context7.com/mcp",
          "enabled": true,
          "headers": {"Authorization": "Bearer ..."},
          "timeout": 30000
        }
      }
    }
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from .tools.base import Tool, truncate

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = "/app/.pequenin/mcp.json"
DEFAULT_TIMEOUT_MS = 30_000
PROTOCOL_VERSION = "2025-06-18"
_MAX_DESC_CHARS = 1024
_MAX_TOTAL_TOOLS = 60  # context-budget guard: a big server can blow the window


# --------------------------------------------------------------------------- #
# config + egress guard
# --------------------------------------------------------------------------- #
@dataclass
class McpServer:
    name: str
    url: str
    headers: dict = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_MS / 1000


def _sanitize(s: str) -> str:
    """opencode tool-name rule: non ``[a-zA-Z0-9_-]`` → ``_``."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(s))


def _url_allowed(url: str) -> tuple[bool, str]:
    """SSRF guard. Block non-http(s), and private/loopback/link-local IP literals
    (and ``localhost``) unless ``PEQUENIN_MCP_ALLOW_PRIVATE`` is set. Hostnames that
    are not IP literals are allowed (we don't resolve DNS here — documented limit)."""
    try:
        u = urlparse(url)
    except Exception:
        return False, "unparseable URL"
    if u.scheme not in ("http", "https"):
        return False, f"scheme '{u.scheme}' not allowed (use http/https)"
    host = (u.hostname or "").strip()
    if not host:
        return False, "missing host"
    if os.environ.get("PEQUENIN_MCP_ALLOW_PRIVATE", "").lower() in ("1", "true", "yes"):
        return True, ""
    low = host.lower()
    if low == "localhost" or low.endswith(".localhost"):
        return False, "loopback host blocked"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False, f"private/loopback IP {host} blocked"
    return True, ""


def _load_mcp_config(config) -> dict:
    """Read ``/app/.pequenin/mcp.json`` from the VM. Best-effort → ``{}``."""
    from .tools.vm import client_for_config

    client, cid = client_for_config(config)
    if client is None:
        return {}
    try:
        resp = client.read_file(cid, MCP_CONFIG_PATH)
    except Exception:
        return {}
    if not isinstance(resp, dict) or not resp.get("found"):
        return {}
    try:
        data = json.loads(resp.get("content") or "{}")
    except Exception:
        logger.warning("%s is not valid JSON; ignoring", MCP_CONFIG_PATH)
        return {}
    return data if isinstance(data, dict) else {}


# Wrapper keys we recognize, in priority order: Claude Code / Cursor / .mcp.json
# (`mcpServers`), opencode (`mcp`), VS Code (`servers`).
_SERVER_KEYS = ("mcpServers", "mcp", "servers")


def _server_map(cfg: object) -> dict:
    """Find the ``{name: spec}`` server map in a parsed mcp.json, tolerantly.

    Accepts any known wrapper key; if none is present, accepts a bare unwrapped map
    when every value looks like a server spec (a dict with a ``url`` or ``command``)."""
    if not isinstance(cfg, dict):
        return {}
    for key in _SERVER_KEYS:
        v = cfg.get(key)
        if isinstance(v, dict):
            return v
    vals = list(cfg.values())
    if vals and all(
        isinstance(v, dict) and ("url" in v or "command" in v) for v in vals
    ):
        return cfg
    return {}


def parse_servers(cfg: dict) -> list[McpServer]:
    """Validate a parsed mcp.json into connectable REMOTE servers (skips the rest).

    Liberal in what it accepts, because models and copy-pasted configs vary:
    - wrapper key ``mcpServers`` (Claude Code / Cursor), ``mcp`` (opencode) or
      ``servers`` (VS Code), or a bare unwrapped map;
    - ``type`` optional — anything that is not ``local``/``stdio`` is treated as a
      remote HTTP server (``remote``/``http``/``sse``/absent all work);
    - turned off via ``enabled: false`` OR ``disabled: true``.
    Only remote HTTP servers are supported (local/stdio are skipped)."""
    out: list[McpServer] = []
    for name, spec in _server_map(cfg).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("enabled") is False or spec.get("disabled") is True:
            continue
        url = spec.get("url")
        stype = str(spec.get("type", "") or "").strip().lower()
        if stype in ("local", "stdio") or (spec.get("command") and not url):
            logger.warning(
                "%s: local/stdio servers are not supported (remote only); skipped",
                name,
            )
            continue
        if not isinstance(url, str) or not url:
            logger.warning("%s: missing url; skipped", name)
            continue
        ok, reason = _url_allowed(url)
        if not ok:
            logger.warning("%s: url blocked (%s); skipped", name, reason)
            continue
        headers = spec.get("headers")
        headers = headers if isinstance(headers, dict) else {}
        timeout = spec.get("timeout")
        timeout_s = (
            int(timeout) / 1000
            if isinstance(timeout, (int, float)) and timeout > 0
            else DEFAULT_TIMEOUT_MS / 1000
        )
        out.append(McpServer(name=name, url=url, headers=headers, timeout_s=timeout_s))
    return out


# --------------------------------------------------------------------------- #
# minimal sync Streamable-HTTP JSON-RPC client
# --------------------------------------------------------------------------- #
class McpError(Exception):
    pass


def _flatten_content(result: object) -> str:
    """MCP ``tools/call`` result → text (text parts joined; non-text noted)."""
    if not isinstance(result, dict):
        return str(result)
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text":
            parts.append(str(item.get("text") or ""))
        elif t == "image":
            parts.append("[image omitted]")
        elif t == "resource":
            res = item.get("resource") or {}
            parts.append(str(res.get("text") or res.get("uri") or "[resource]"))
        else:
            parts.append(f"[{t}]")
    out = "\n".join(p for p in parts if p)
    if result.get("isError"):
        out = f"[the tool reported an error]\n{out}"
    return out or "(no content)"


class McpHttpClient:
    """One connection to a remote MCP server, reused for the whole turn.

    Streamable HTTP: each JSON-RPC request is POSTed; the reply is either
    ``application/json`` (one message) or ``text/event-stream`` (SSE, one message).
    Session continuity via the ``Mcp-Session-Id`` header (echoed back on later calls).
    """

    def __init__(self, url: str, headers: dict | None = None, timeout_s: float = 30.0):
        self.url = url
        self.timeout_s = timeout_s
        self._sid: str | None = None
        self._proto = PROTOCOL_VERSION
        self._id = 0
        self._session = requests.Session()
        self._base_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if headers:
            self._base_headers.update({str(k): str(v) for k, v in headers.items()})

    def _headers(self) -> dict:
        h = dict(self._base_headers)
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        if self._proto:
            h["MCP-Protocol-Version"] = self._proto
        return h

    def _post(self, payload: dict, expect_response: bool = True) -> object:
        resp = self._session.post(
            self.url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_s,
            stream=True,
        )
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._sid = sid
        if not resp.ok:
            body = ""
            try:
                body = resp.text[:500]
            except Exception:
                pass
            resp.close()
            raise McpError(f"HTTP {resp.status_code}: {body}")
        if not expect_response:
            resp.close()
            return None
        ctype = (resp.headers.get("Content-Type") or "").lower()
        req_id = payload.get("id")
        try:
            if "text/event-stream" in ctype:
                msg = self._read_sse(resp, req_id)
            else:
                msg = resp.json()
        finally:
            resp.close()
        if isinstance(msg, dict) and msg.get("error"):
            err = msg["error"] or {}
            raise McpError(f"{err.get('code')}: {err.get('message')}")
        return msg.get("result") if isinstance(msg, dict) else None

    @staticmethod
    def _read_sse(resp, req_id) -> dict | None:
        """Return the first SSE ``data:`` message matching ``req_id`` (or any)."""
        buf: list[str] = []
        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            line = raw.rstrip("\r")
            if line == "":
                if buf:
                    try:
                        msg = json.loads("\n".join(buf))
                    except Exception:
                        msg = None
                    buf = []
                    if isinstance(msg, dict) and (
                        req_id is None or msg.get("id") == req_id
                    ):
                        return msg
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                buf.append(line[5:].lstrip())
        if buf:
            try:
                return json.loads("\n".join(buf))
            except Exception:
                return None
        return None

    def _rpc(self, method: str, params: dict) -> object:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        return self._post(payload, expect_response=True)

    def _notify(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            self._post(payload, expect_response=False)
        except Exception:
            pass

    def initialize(self) -> None:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pequenin", "version": "1"},
            },
        )
        if isinstance(result, dict) and result.get("protocolVersion"):
            self._proto = str(result["protocolVersion"])
        self._notify("notifications/initialized")

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list", {}) or {}
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return _flatten_content(result)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# tool adapter + discovery
# --------------------------------------------------------------------------- #
def _normalize_schema(schema: object) -> dict:
    """Coerce an MCP ``inputSchema`` into an OpenAI-style object schema."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out = dict(schema)
    out["type"] = "object"
    if not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


class McpTool(Tool):
    """A remote MCP tool exposed to the model as a normal minicode tool.

    Name is ``<server>_<tool>`` (sanitized). ``execute`` calls the server over the
    shared per-turn ``McpHttpClient``.
    """

    read_only = False

    def __init__(self, server, tool_name, description, parameters, client):
        self.name = f"{_sanitize(server)}_{_sanitize(tool_name)}"
        self.description = (description or f"MCP tool '{tool_name}' from '{server}'.")[
            :_MAX_DESC_CHARS
        ]
        self.parameters = parameters
        self._client = client
        self._remote_name = tool_name
        self._server = server

    def execute(self, args: dict, ctx) -> str:
        try:
            out = self._client.call_tool(self._remote_name, args or {})
        except Exception as e:
            return f"Error calling MCP tool {self.name}: {e}"
        return truncate(str(out), from_tail=True)


def discover_mcp_tools(config) -> list[McpTool]:
    """Read mcp.json from the VM, connect to each enabled remote server, list its
    tools and wrap them. Once per turn. Best-effort: a failing server is skipped, it
    never breaks the turn. Capped at ``_MAX_TOTAL_TOOLS`` total."""
    servers = parse_servers(_load_mcp_config(config))
    tools: list[McpTool] = []
    for s in servers:
        client = McpHttpClient(s.url, s.headers, s.timeout_s)
        try:
            client.initialize()
            raw = client.list_tools()
        except Exception as e:
            logger.warning("%s: connect/list failed: %s", s.name, e)
            client.close()
            continue
        for t in raw:
            if not isinstance(t, dict):
                continue
            tname = t.get("name")
            if not tname:
                continue
            tools.append(
                McpTool(
                    s.name,
                    str(tname),
                    t.get("description") or "",
                    _normalize_schema(t.get("inputSchema")),
                    client,
                )
            )
            if len(tools) >= _MAX_TOTAL_TOOLS:
                logger.warning("tool cap %s reached; remaining dropped", _MAX_TOTAL_TOOLS)
                return tools
    return tools
