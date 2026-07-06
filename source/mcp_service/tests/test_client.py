"""Unit tests for PlatformClient using httpx's in-process MockTransport.

These don't need a running web_service or the MCP runtime — they validate the
request shapes the tools rely on and the error-envelope mapping.
"""

import json

import httpx
import pytest

from pequeroku_mcp.client import PlatformClient, PlatformError


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return PlatformClient("http://web:8000", "pk_test_secret", transport=transport)


def test_run_code_posts_to_runs():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read().decode())
        assert request.headers["authorization"] == "Bearer pk_test_secret"
        return httpx.Response(200, json={"status": "succeeded", "stdout": "hi\n"})

    client = make_client(handler)
    out = client.run_code(
        "echo hi", files=[{"path": "a", "content": "b"}], type="small"
    )
    assert out["status"] == "succeeded"
    assert seen["url"] == "http://web:8000/api/v1/runs/"
    assert seen["body"]["command"] == "echo hi"
    assert seen["body"]["files"] == [{"path": "a", "content": "b"}]


def test_list_types_returns_flavors():
    def handler(request):
        assert str(request.url).endswith("/api/v1/types/")
        return httpx.Response(
            200,
            json=[
                {"id": 1, "name": "small", "vcpus": 1, "credits_cost": 1},
                {"id": 3, "name": "large", "vcpus": 4, "credits_cost": 3},
            ],
        )

    types = make_client(handler).list_types()
    assert [t["name"] for t in types] == ["small", "large"]


def test_list_containers_unwraps_pagination():
    def handler(request):
        return httpx.Response(
            200, json={"results": [{"id": 1, "name": "x"}], "count": 1}
        )

    assert make_client(handler).list_containers() == [{"id": 1, "name": "x"}]


def test_get_or_create_returns_existing_by_name():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": [{"id": 7, "name": "blog"}]})
        raise AssertionError("should not POST when it already exists")

    out = make_client(handler).get_or_create_container("blog", type="small")
    assert out["id"] == 7


def test_get_or_create_creates_when_missing():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(201, json={"id": 9, "name": "blog"})

    out = make_client(handler).get_or_create_container("blog", type="small")
    assert out["id"] == 9


def test_get_or_create_without_type_errors():
    def handler(request):
        return httpx.Response(200, json={"results": []})

    with pytest.raises(PlatformError) as e:
        make_client(handler).get_or_create_container("blog")
    assert e.value.code == "invalid_request"


def test_read_path_file_vs_dir():
    def handler(request):
        if "/files/" in str(request.url):
            if "missing" in str(request.url):
                return httpx.Response(200, json={"found": False})
            return httpx.Response(200, json={"found": True, "content": "data"})
        if "/dirs/" in str(request.url):
            return httpx.Response(200, json=[{"name": "a", "path_type": "file"}])
        raise AssertionError(str(request.url))

    client = make_client(handler)
    f = client.read_path(1, "/app/a.txt")
    assert f["kind"] == "file" and f["content"] == "data"
    d = client.read_path(1, "/app/missing")
    assert d["kind"] == "dir" and d["entries"][0]["name"] == "a"


def test_error_envelope_maps_to_platform_error():
    def handler(request):
        return httpx.Response(
            403, json={"error": {"code": "quota_exceeded", "message": "no credits"}}
        )

    with pytest.raises(PlatformError) as e:
        make_client(handler).list_containers()
    assert e.value.code == "quota_exceeded"
    assert "no credits" in e.value.message


def test_destroy_calls_delete():
    calls = {}

    def handler(request):
        calls["method"] = request.method
        calls["url"] = str(request.url)
        return httpx.Response(204)

    make_client(handler).destroy_container(5)
    assert calls["method"] == "DELETE"
    assert calls["url"].endswith("/api/v1/containers/5/")


def test_get_preview_adds_absolute_preview_url():
    def handler(request):
        assert str(request.url).endswith("/api/v1/containers/7/ports/")
        return httpx.Response(
            200,
            json=[
                {
                    "port": 8000,
                    "process": "python3",
                    "preview_path": "/api/containers/7/preview/8000/",
                },
                {"port": 5173, "process": "node"},  # no preview_path → derived
            ],
        )

    ports = make_client(handler).get_preview(7)
    assert ports[0]["preview_url"] == "http://web:8000/api/containers/7/preview/8000/"
    assert ports[1]["preview_url"] == "http://web:8000/api/containers/7/preview/5173/"


def test_fetch_preview_returns_live_response_with_token():
    def handler(request):
        # Hits the preview endpoint (NOT /api/v1) with the caller's bearer token.
        assert str(request.url) == "http://web:8000/api/containers/7/preview/8000/health"
        assert request.headers["authorization"] == "Bearer pk_test_secret"
        return httpx.Response(
            200, text='{"ok": true}', headers={"content-type": "application/json"}
        )

    out = make_client(handler).fetch_preview(7, 8000, "/health")
    assert out["status"] == 200
    assert out["content_type"] == "application/json"
    assert out["body"] == '{"ok": true}'
    assert out["url"].endswith("/api/containers/7/preview/8000/health")


def test_fetch_preview_normalizes_path_and_summarizes_binary():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(
            200, content=b"\x89PNG" + b"\x00" * 30, headers={"content-type": "image/png"}
        )

    out = make_client(handler).fetch_preview(7, 8000, "logo.png")  # no leading slash
    assert seen["url"] == "http://web:8000/api/containers/7/preview/8000/logo.png"
    assert out["content_type"] == "image/png"
    assert "bytes of image/png" in out["body"]  # binary summarized, not decoded
