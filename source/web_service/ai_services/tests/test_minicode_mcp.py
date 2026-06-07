"""Tests for the MCP (remote HTTP) integration: config parsing, the SSRF egress
guard, the sync Streamable-HTTP JSON-RPC client (against a fake requests.Session),
the tool adapter and discovery. No real network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_services.minicode import mcp
from ai_services.minicode.config import Config


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def make_config(read_resp=None, raise_read=False):
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")

    class _Client:
        def read_file(self, cid, path):
            if raise_read:
                raise RuntimeError("boom")
            return read_resp

    if read_resp is None and not raise_read:
        config.container = None
    else:
        config.container = SimpleNamespace(container_id="vm-1", node=object())
        config._vm_client = _Client()
    return config


# --------------------------------------------------------------------------- #
# _sanitize / _normalize_schema
# --------------------------------------------------------------------------- #
def test_sanitize_replaces_invalid_chars():
    assert mcp._sanitize("a b/c.d") == "a_b_c_d"
    assert mcp._sanitize("keep-_ok") == "keep-_ok"


def test_normalize_schema():
    assert mcp._normalize_schema(None) == {"type": "object", "properties": {}}
    out = mcp._normalize_schema({"properties": "bad", "required": ["x"]})
    assert (
        out["type"] == "object" and out["properties"] == {} and out["required"] == ["x"]
    )


# --------------------------------------------------------------------------- #
# _url_allowed (SSRF guard)
# --------------------------------------------------------------------------- #
def test_url_allowed_public_https():
    ok, _ = mcp._url_allowed("https://mcp.example.com/mcp")
    assert ok


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",  # bad scheme
        "https://",  # missing host
        "http://localhost/mcp",  # loopback host
        "http://foo.localhost/mcp",  # .localhost suffix
        "http://127.0.0.1/mcp",  # loopback IP
        "http://10.0.0.5/mcp",  # private IP
        "http://169.254.1.1/mcp",  # link-local
    ],
)
def test_url_allowed_blocks(url):
    ok, reason = mcp._url_allowed(url)
    assert ok is False and reason


def test_url_allowed_private_override(monkeypatch):
    monkeypatch.setenv("PEQUENIN_MCP_ALLOW_PRIVATE", "true")
    ok, _ = mcp._url_allowed("http://127.0.0.1/mcp")
    assert ok


# --------------------------------------------------------------------------- #
# _server_map
# --------------------------------------------------------------------------- #
def test_server_map_recognizes_wrapper_keys():
    spec = {"alpha": {"url": "https://x"}}
    assert mcp._server_map({"mcpServers": spec}) == spec
    assert mcp._server_map({"mcp": spec}) == spec
    assert mcp._server_map({"servers": spec}) == spec


def test_server_map_bare_unwrapped_map():
    bare = {"alpha": {"url": "https://x"}, "beta": {"command": "run"}}
    assert mcp._server_map(bare) == bare


def test_server_map_returns_empty_for_unknown_shapes():
    assert mcp._server_map("nope") == {}
    assert mcp._server_map({"alpha": "not-a-dict"}) == {}


# --------------------------------------------------------------------------- #
# parse_servers
# --------------------------------------------------------------------------- #
def test_parse_servers_valid_remote_with_timeout():
    cfg = {
        "mcp": {
            "ctx": {
                "url": "https://mcp.example.com/mcp",
                "timeout": 5000,
                "headers": {"Authorization": "Bearer t"},
            }
        }
    }
    servers = mcp.parse_servers(cfg)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "ctx" and s.url == "https://mcp.example.com/mcp"
    assert s.timeout_s == 5.0 and s.headers == {"Authorization": "Bearer t"}


def test_parse_servers_default_timeout_for_bad_value():
    cfg = {"mcp": {"a": {"url": "https://x.example.com", "timeout": -1}}}
    assert mcp.parse_servers(cfg)[0].timeout_s == mcp.DEFAULT_TIMEOUT_MS / 1000


def test_parse_servers_skips_disabled_and_enabled_false():
    cfg = {
        "mcp": {
            "a": {"url": "https://a.example.com", "enabled": False},
            "b": {"url": "https://b.example.com", "disabled": True},
        }
    }
    assert mcp.parse_servers(cfg) == []


def test_parse_servers_skips_local_stdio_and_command_only():
    cfg = {
        "mcp": {
            "a": {"type": "local", "url": "https://a.example.com"},
            "b": {"type": "stdio", "url": "https://b.example.com"},
            "c": {"command": "run-me"},
        }
    }
    assert mcp.parse_servers(cfg) == []


def test_parse_servers_skips_missing_and_blocked_url():
    cfg = {
        "mcp": {
            "a": {"type": "remote"},  # missing url
            "b": {"url": "http://127.0.0.1/mcp"},  # blocked
        }
    }
    assert mcp.parse_servers(cfg) == []


def test_parse_servers_ignores_non_dict_spec():
    assert mcp.parse_servers({"mcp": {"a": "nope"}}) == []


# --------------------------------------------------------------------------- #
# _load_mcp_config
# --------------------------------------------------------------------------- #
def test_load_mcp_config_no_container():
    assert mcp._load_mcp_config(make_config()) == {}


def test_load_mcp_config_valid_json():
    cfg = {"mcp": {"a": {"url": "https://x"}}}
    config = make_config({"found": True, "content": json.dumps(cfg)})
    assert mcp._load_mcp_config(config) == cfg


def test_load_mcp_config_invalid_json_returns_empty():
    config = make_config({"found": True, "content": "{not json"})
    assert mcp._load_mcp_config(config) == {}


def test_load_mcp_config_not_found():
    assert mcp._load_mcp_config(make_config({"found": False})) == {}


def test_load_mcp_config_read_error():
    assert mcp._load_mcp_config(make_config(raise_read=True)) == {}


def test_load_mcp_config_non_dict_payload():
    config = make_config({"found": True, "content": "[1, 2, 3]"})
    assert mcp._load_mcp_config(config) == {}


# --------------------------------------------------------------------------- #
# _flatten_content
# --------------------------------------------------------------------------- #
def test_flatten_content_joins_text_and_notes_other_types():
    result = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "image"},
            {"type": "resource", "resource": {"uri": "file://x"}},
            {"type": "weird"},
            "not-a-dict",
        ]
    }
    out = mcp._flatten_content(result)
    assert "hello" in out and "[image omitted]" in out
    assert "file://x" in out and "[weird]" in out


def test_flatten_content_marks_errors_and_handles_edge_cases():
    assert mcp._flatten_content("raw") == "raw"
    assert mcp._flatten_content({"content": []}) == "(no content)"
    err = mcp._flatten_content(
        {"isError": True, "content": [{"type": "text", "text": "bad"}]}
    )
    assert err.startswith("[the tool reported an error]") and "bad" in err


# --------------------------------------------------------------------------- #
# McpHttpClient against a fake requests.Session
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(
        self,
        *,
        ok=True,
        status_code=200,
        headers=None,
        json_body=None,
        sse_lines=None,
        text="",
    ):
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._json_body = json_body
        self._sse_lines = sse_lines
        self.text = text
        self.closed = False

    def json(self):
        return self._json_body

    def iter_lines(self, decode_unicode=False):
        for line in self._sse_lines or []:
            yield line

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None, stream=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)

    def close(self):
        self.closed = True


def _client_with(responses):
    c = mcp.McpHttpClient("https://mcp.example.com/mcp", {"X-Key": "v"}, timeout_s=3)
    c._session = FakeSession(responses)
    return c


def test_http_client_json_rpc_result_and_session_id():
    resp = FakeResponse(
        headers={"Content-Type": "application/json", "Mcp-Session-Id": "sid-1"},
        json_body={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
    )
    c = _client_with([resp])
    out = c._rpc("ping", {})
    assert out == {"ok": True}
    assert c._sid == "sid-1"  # session id captured for continuity
    # base headers include the custom header + accept/content-type
    assert c._session.posts[0]["headers"]["X-Key"] == "v"


def test_http_client_rpc_error_raises():
    resp = FakeResponse(
        json_body={"id": 1, "error": {"code": -32000, "message": "nope"}}
    )
    c = _client_with([resp])
    with pytest.raises(mcp.McpError, match="nope"):
        c._rpc("ping", {})


def test_http_client_http_error_raises():
    resp = FakeResponse(ok=False, status_code=500, text="server boom")
    c = _client_with([resp])
    with pytest.raises(mcp.McpError, match="HTTP 500"):
        c._rpc("ping", {})
    assert resp.closed


def test_http_client_sse_response_parsed():
    sse = FakeResponse(
        headers={"Content-Type": "text/event-stream"},
        sse_lines=[
            ": a comment",
            'data: {"id": 1, "result": {"v": 42}}',
            "",
        ],
    )
    c = _client_with([sse])
    assert c._rpc("ping", {}) == {"v": 42}


def test_read_sse_skips_nonmatching_then_returns_match():
    resp = FakeResponse(
        sse_lines=[
            'data: {"id": 9, "result": "other"}',
            "",
            'data: {"id": 1, "result": "mine"}',
            "",
        ]
    )
    msg = mcp.McpHttpClient._read_sse(resp, req_id=1)
    assert msg["result"] == "mine"


def test_read_sse_trailing_buffer_without_blank_line():
    resp = FakeResponse(sse_lines=['data: {"id": 1, "result": "tail"}'])
    msg = mcp.McpHttpClient._read_sse(resp, req_id=None)
    assert msg["result"] == "tail"


def test_http_client_initialize_list_and_call():
    init = FakeResponse(
        json_body={"id": 1, "result": {"protocolVersion": "2099-01-01"}}
    )
    notif_ok = FakeResponse(
        json_body={"id": None, "result": {}}
    )  # for notifications/initialized
    listed = FakeResponse(json_body={"id": 3, "result": {"tools": [{"name": "t1"}]}})
    called = FakeResponse(
        json_body={"id": 4, "result": {"content": [{"type": "text", "text": "done"}]}}
    )
    c = _client_with([init, notif_ok, listed, called])
    c.initialize()
    assert c._proto == "2099-01-01"
    assert c.list_tools() == [{"name": "t1"}]
    assert c.call_tool("t1", {"a": 1}) == "done"
    c.close()
    assert c._session.closed


def test_http_client_list_tools_handles_bad_shapes():
    resp = FakeResponse(json_body={"id": 1, "result": {"tools": "nope"}})
    c = _client_with([resp])
    assert c.list_tools() == []


# --------------------------------------------------------------------------- #
# McpTool adapter
# --------------------------------------------------------------------------- #
class _FakeMcpClient:
    def __init__(self, result="output", raise_exc=False):
        self.result = result
        self.raise_exc = raise_exc
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.raise_exc:
            raise RuntimeError("upstream down")
        return self.result


def test_mcp_tool_name_and_execute_success():
    client = _FakeMcpClient(result="42")
    tool = mcp.McpTool("My Server", "do thing", "desc", {"type": "object"}, client)
    assert tool.name == "My_Server_do_thing"
    assert tool.execute({"x": 1}, ctx=None) == "42"
    assert client.calls == [("do thing", {"x": 1})]


def test_mcp_tool_execute_error_is_caught():
    tool = mcp.McpTool("s", "t", "", {}, _FakeMcpClient(raise_exc=True))
    out = tool.execute({}, ctx=None)
    assert out.startswith("Error calling MCP tool s_t") and "upstream down" in out


# --------------------------------------------------------------------------- #
# discover_mcp_tools
# --------------------------------------------------------------------------- #
def test_discover_mcp_tools_builds_tools(monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_load_mcp_config",
        lambda config: {"mcp": {"srv": {"url": "https://srv.example.com/mcp"}}},
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            pass

        def list_tools(self):
            return [
                {"name": "alpha", "description": "d", "inputSchema": {}},
                {"not": "a-name"},  # skipped (no name)
                "nope",
            ]  # skipped (not a dict)

        def close(self):
            pass

    monkeypatch.setattr(mcp, "McpHttpClient", _FakeClient)
    tools = mcp.discover_mcp_tools(make_config({"found": True, "content": "{}"}))
    assert [t.name for t in tools] == ["srv_alpha"]


def test_discover_mcp_tools_skips_failing_server(monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_load_mcp_config",
        lambda config: {"mcp": {"srv": {"url": "https://srv.example.com/mcp"}}},
    )
    closed = {"v": False}

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            raise RuntimeError("connect failed")

        def close(self):
            closed["v"] = True

    monkeypatch.setattr(mcp, "McpHttpClient", _BoomClient)
    assert mcp.discover_mcp_tools(make_config({"found": True, "content": "{}"})) == []
    assert closed["v"]  # the client is closed on failure


def test_discover_mcp_tools_enforces_cap(monkeypatch):
    monkeypatch.setattr(mcp, "_MAX_TOTAL_TOOLS", 2)
    monkeypatch.setattr(
        mcp,
        "_load_mcp_config",
        lambda config: {"mcp": {"srv": {"url": "https://srv.example.com/mcp"}}},
    )

    class _ManyClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            pass

        def list_tools(self):
            return [{"name": f"t{i}"} for i in range(10)]

        def close(self):
            pass

    monkeypatch.setattr(mcp, "McpHttpClient", _ManyClient)
    tools = mcp.discover_mcp_tools(make_config({"found": True, "content": "{}"}))
    assert len(tools) == 2  # capped
