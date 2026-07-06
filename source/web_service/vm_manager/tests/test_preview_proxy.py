import base64
import types

from django.http import StreamingHttpResponse
from django.test import RequestFactory
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from vm_manager import preview_proxy
from vm_manager.preview_proxy import (
    PREVIEW_TOKEN_COOKIE,
    PREVIEW_TOKEN_QUERY,
    CSRFExemptSessionAuthentication,
    PreviewPassthroughRenderer,
    _rewrite_html,
    _strip_preview_token,
    build_preview_response,
)


def test_csrf_exempt_session_auth_skips_enforcement():
    # enforce_csrf is a no-op (returns None) so previewed-app form POSTs aren't
    # blocked by pequeroku's CSRF check.
    assert CSRFExemptSessionAuthentication().enforce_csrf(None) is None


def test_passthrough_renderer_satisfies_event_stream_accept():
    # Gradio's SSE queue requests `Accept: text/event-stream` (no */* fallback).
    # The wildcard renderer must satisfy DRF negotiation so it doesn't 406 before
    # our proxy view runs.
    req = Request(APIRequestFactory().get("/x", HTTP_ACCEPT="text/event-stream"))
    renderer, media = DefaultContentNegotiation().select_renderer(
        req, [PreviewPassthroughRenderer()]
    )
    assert isinstance(renderer, PreviewPassthroughRenderer)


# --- _rewrite_html (pure) --------------------------------------------------- #
def test_rewrite_html_injects_base_and_reroots_absolute_paths():
    prefix = "/api/containers/15/preview/8000/"
    html = (
        "<html><head><title>x</title></head><body>"
        '<a href="/">home</a>'
        '<a href="/about">about</a>'
        '<img src="/static/logo.png">'
        '<a href="rel/page">rel</a>'
        "</body></html>"
    )
    out = _rewrite_html(html, prefix, "8000")

    assert f'<base href="{prefix}">' in out
    assert f'href="{prefix}"' in out  # bare "/" re-rooted (the old bug)
    assert f'href="{prefix}about"' in out
    assert f'src="{prefix}static/logo.png"' in out
    assert 'href="rel/page"' in out  # relative untouched; <base> resolves it


def test_rewrite_html_injects_runtime_shim():
    out = _rewrite_html(
        "<html><head></head><body></body></html>",
        "/api/containers/15/preview/8000/",
        "8000",
    )
    assert '<base href="/api/containers/15/preview/8000/">' in out
    # Shim runs as a script; PREFIX has NO trailing slash so PREFIX + "/posts" works.
    assert 'var PREFIX="/api/containers/15/preview/8000"' in out
    assert 'PORT="8000"' in out  # self-origin (host:port) stripping is port-aware
    assert "window.fetch=" in out  # API edge patched
    assert "Element.prototype.setAttribute" in out  # img/href setters patched


def test_rewrite_html_inserts_head_when_missing():
    out = _rewrite_html("<body><a href='/x'>x</a></body>", "/p/", "8000")
    # A <head> is synthesized, starting with our <base> (the shim follows it).
    assert '<head><base href="/p/"><script>' in out
    assert "</head><body>" in out


def test_rewrite_html_srcset_absolute_entries():
    out = _rewrite_html('<img srcset="/a.png 1x, /b.png 2x">', "/p/", "8000")
    assert "/p/a.png 1x" in out
    assert "/p/b.png 2x" in out


def test_rewrite_html_reroots_upstream_self_origin():
    # Gradio (and friends) bake their OWN host:port into asset URLs and the inline
    # JS config root. From the browser those hit the user's localhost
    # (ERR_CONNECTION_REFUSED), so they must collapse onto the preview base. The
    # target is ABSOLUTE (origin + prefix): Gradio does new URL(config.root),
    # which throws "Invalid URL" on a bare path.
    prefix = "/api/containers/251/preview/7860/"
    origin = "https://pequeroku.example"
    base = origin + prefix.rstrip("/")
    html = (
        "<html><head>"
        '<script src="http://127.0.0.1:7860/static/js/iframeResizer.js"></script>'
        "</head><body>"
        '<script>window.gradio_config={"root":"http://127.0.0.1:7860","x":1};</script>'
        '<link rel="stylesheet" href="https://localhost:7860/theme.css?v=abc">'
        "</body></html>"
    )
    out = _rewrite_html(html, prefix, "7860", origin)

    assert "127.0.0.1:7860" not in out  # no upstream self-origin survives
    assert "//localhost:7860" not in out
    assert f'src="{base}/static/js/iframeResizer.js"' in out
    assert f'"root":"{base}"' in out  # absolute -> Gradio's new URL(root) works
    assert f'href="{base}/theme.css?v=abc"' in out  # query preserved


def test_rewrite_html_self_origin_other_port_untouched():
    # A reference to a DIFFERENT port is not this app — leave it alone.
    out = _rewrite_html(
        '<a href="http://127.0.0.1:9999/x">x</a>',
        "/api/containers/251/preview/7860/",
        "7860",
        "https://pequeroku.example",
    )
    assert "http://127.0.0.1:9999/x" in out


def test_rewrite_html_manifest_forces_credentials():
    # The manifest is fetched without cookies by default -> our auth 403s it.
    out = _rewrite_html(
        '<html><head><link rel="manifest" href="/manifest.json"></head></html>',
        "/api/containers/251/preview/7860/",
        "7860",
    )
    assert 'crossorigin="use-credentials"' in out
    assert 'href="/api/containers/251/preview/7860/manifest.json"' in out


# --- build_preview_response ------------------------------------------------- #
def _service(envelope):
    return types.SimpleNamespace(proxy=lambda vm_id, payload: envelope)


def _container(pk=15, cid="vm-uuid"):
    return types.SimpleNamespace(pk=pk, container_id=cid)


def _env(body: bytes, *, status=200, headers=None, ok=True, reason=""):
    return {
        "ok": ok,
        "status": status,
        "reason": reason,
        "headers": headers or [["Content-Type", "text/html; charset=utf-8"]],
        "body_b64": base64.b64encode(body).decode("ascii"),
    }


def test_build_preview_response_rewrites_html_and_strips_frame_busting():
    req = RequestFactory().get("/api/containers/15/preview/8000/")
    env = _env(
        b'<html><head></head><body><a href="/">home</a></body></html>',
        headers=[
            ["Content-Type", "text/html; charset=utf-8"],
            ["X-Frame-Options", "DENY"],
            ["Content-Security-Policy", "frame-ancestors 'none'"],
        ],
    )
    resp = build_preview_response(req, _container(), "8000", "", _service(env))

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/html")
    content = resp.content.decode()
    assert '<base href="/api/containers/15/preview/8000/">' in content
    assert 'href="/api/containers/15/preview/8000/"' in content
    assert resp.get("X-Frame-Options") is None  # frame-busting removed
    assert resp.get("Content-Security-Policy") is None
    assert resp["X-Robots-Tag"] == "noindex"
    assert "no-store" in resp["Cache-Control"]  # never cache the live preview


# --- streaming / SSE relay --------------------------------------------------- #
class _FakeUpstream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_raw(self):
        for c in self._chunks:
            yield c


class _FakeAsyncClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kwargs):
        return _FakeUpstream(self._chunks)


def _sse_service():
    return types.SimpleNamespace(
        stream_endpoint=lambda vm_id: (
            f"http://node/vms/{vm_id}/proxy-stream",
            {"Authorization": "Bearer t"},
        )
    )


def _sse_request(path="/api/containers/15/preview/7860/gradio_api/queue/data"):
    return RequestFactory().get(path, HTTP_ACCEPT="text/event-stream")


def test_sse_request_returns_streaming_response():
    # An `Accept: text/event-stream` request is routed to the streaming proxy and
    # gets the headers SSE needs (no nginx buffering, no caching, embeddable).
    resp = build_preview_response(
        _sse_request(), _container(), "7860", "gradio_api/queue/data", _sse_service()
    )
    assert isinstance(resp, StreamingHttpResponse)
    assert resp["Content-Type"] == "text/event-stream"
    assert resp["X-Accel-Buffering"] == "no"
    assert "no-cache" in resp["Cache-Control"]
    assert getattr(resp, "xframe_options_exempt", False) is True


def test_non_sse_request_uses_buffered_path():
    # A normal (HTML) request must NOT be streamed — it needs the rewrite pass.
    req = RequestFactory().get("/api/containers/15/preview/8000/", HTTP_ACCEPT="text/html")
    env = _env(b"<html><head></head><body></body></html>")
    resp = build_preview_response(req, _container(), "8000", "", _service(env))
    assert not isinstance(resp, StreamingHttpResponse)


async def test_sse_relay_streams_chunks(monkeypatch):
    # The async relay pipes upstream SSE chunks through verbatim, in order.
    chunks = [b"data: hello\n\n", b"data: world\n\n"]
    monkeypatch.setattr(
        preview_proxy.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(chunks),
    )
    resp = build_preview_response(
        _sse_request(), _container(), "7860", "gradio_api/queue/data", _sse_service()
    )
    out = [chunk async for chunk in resp.streaming_content]
    assert out == chunks


def test_build_preview_response_reroots_self_origin_with_forwarded_proto():
    # End-to-end: a Gradio-style body whose config bakes http://127.0.0.1:PORT must
    # come back rewritten to an ABSOLUTE https URL when X-Forwarded-Proto says so
    # (TLS terminated upstream -> request.scheme would be http -> mixed content).
    req = RequestFactory().get(
        "/api/containers/15/preview/7860/", HTTP_X_FORWARDED_PROTO="https"
    )
    env = _env(
        b'<html><head></head><body>'
        b'<script>window.gradio_config={"root":"http://127.0.0.1:7860"};</script>'
        b"</body></html>",
    )
    resp = build_preview_response(req, _container(), "7860", "", _service(env))
    content = resp.content.decode()
    assert "127.0.0.1:7860" not in content
    # origin = https (forwarded) + testserver (RequestFactory host)
    assert '"root":"https://testserver/api/containers/15/preview/7860"' in content


def test_build_preview_response_cf_visitor_overrides_clobbered_proto():
    # Prod reality: nginx clobbers X-Forwarded-Proto to http (Cloudflare→origin is
    # http), but Cloudflare's CF-Visitor still says https. We must emit https so
    # the rewritten asset URLs aren't blocked as mixed content on the https page.
    req = RequestFactory().get(
        "/api/containers/15/preview/7860/",
        HTTP_X_FORWARDED_PROTO="http",
        HTTP_CF_VISITOR='{"scheme":"https"}',
    )
    env = _env(
        b'<html><head></head><body>'
        b'<script>window.gradio_config={"root":"http://127.0.0.1:7860"};</script>'
        b"</body></html>",
    )
    resp = build_preview_response(req, _container(), "7860", "", _service(env))
    content = resp.content.decode()
    assert '"root":"https://testserver/api/containers/15/preview/7860"' in content
    assert "http://testserver" not in content  # no mixed-content http origin


def test_build_preview_response_binary_passthrough():
    """openapi.json must come back as JSON bytes, not a base64→PNG misfire."""
    req = RequestFactory().get("/api/containers/15/preview/8000/openapi.json")
    body = b'{"openapi": "3.0.0", "paths": {}}'
    env = _env(body, headers=[["Content-Type", "application/json"]])

    resp = build_preview_response(
        req, _container(), "8000", "openapi.json", _service(env)
    )

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert resp.content == body  # verbatim, untouched


def test_build_preview_response_app_down():
    req = RequestFactory().get("/api/containers/15/preview/8000/")
    env = {"ok": False, "status": 502, "reason": "Cannot reach app on port 8000"}
    resp = build_preview_response(req, _container(), "8000", "", _service(env))
    assert resp.status_code == 502
    assert b"Cannot reach app" in resp.content
    assert "no-store" in resp["Cache-Control"]  # don't cache transient failures


class _FakeSession(dict):
    modified = False


def test_cookie_jar_stores_from_set_cookie_and_replays():
    rf = RequestFactory()
    sess = _FakeSession()
    captured = {}

    def fake_proxy(vm_id, payload):
        captured["headers"] = dict(payload["headers"])
        return {
            "ok": True,
            "status": 200,
            "headers": [
                ["Content-Type", "text/html"],
                ["Set-Cookie", "sessionid=XYZ; Path=/; HttpOnly"],
                ["Set-Cookie", "csrftoken=ABC; Path=/"],
            ],
            "body_b64": base64.b64encode(b"<html></html>").decode("ascii"),
        }

    service = types.SimpleNamespace(proxy=fake_proxy)

    # First hit: jar empty, but the response seeds it (cookies kept server-side).
    req1 = rf.get("/api/containers/15/preview/8000/admin/")
    req1.session = sess
    build_preview_response(req1, _container(), "8000", "admin/", service)
    assert "Cookie" not in captured["headers"]
    assert sess["preview_cookies"]["15:8000"] == {
        "sessionid": "XYZ",
        "csrftoken": "ABC",
    }

    # Second hit: the jar is replayed to the guest, never exposed to the browser.
    req2 = rf.get("/api/containers/15/preview/8000/admin/")
    req2.session = sess
    resp = build_preview_response(req2, _container(), "8000", "admin/", service)
    assert captured["headers"]["Cookie"] == "sessionid=XYZ; csrftoken=ABC"
    assert resp.get("Set-Cookie") is None  # guest cookies never reach the browser


def test_cookie_jar_deletes_on_logout():
    rf = RequestFactory()
    sess = _FakeSession()
    sess["preview_cookies"] = {"15:8000": {"sessionid": "XYZ"}}

    def fake_proxy(vm_id, payload):
        return {
            "ok": True,
            "status": 200,
            "headers": [
                ["Content-Type", "text/html"],
                ["Set-Cookie", "sessionid=; expires=Thu, 01 Jan 1970 00:00:00 GMT"],
            ],
            "body_b64": base64.b64encode(b"<html></html>").decode("ascii"),
        }

    service = types.SimpleNamespace(proxy=fake_proxy)
    req = rf.get("/api/containers/15/preview/8000/admin/logout/")
    req.session = sess
    build_preview_response(req, _container(), "8000", "admin/logout/", service)
    assert sess["preview_cookies"]["15:8000"] == {}


def test_build_preview_response_reroots_location_redirect():
    req = RequestFactory().get("/api/containers/15/preview/8000/old")
    env = _env(
        b"<html></html>",
        status=302,
        headers=[["Content-Type", "text/html"], ["Location", "/new"]],
    )
    resp = build_preview_response(req, _container(), "8000", "old", _service(env))
    assert resp.status_code == 302
    assert resp["Location"] == "/api/containers/15/preview/8000/new"


# --- preview token (query stripping + bootstrap cookie) --------------------- #
def test_strip_preview_token_removes_only_our_param():
    # Our namespaced token is dropped; the guest app's own params pass through.
    out = _strip_preview_token(f"a=1&{PREVIEW_TOKEN_QUERY}=pk_x_y&b=2")
    assert PREVIEW_TOKEN_QUERY not in out
    assert "a=1" in out and "b=2" in out
    # No token param → returned unchanged (fast path).
    assert _strip_preview_token("a=1&b=2") == "a=1&b=2"
    assert _strip_preview_token("") == ""


def test_query_token_never_forwarded_to_guest_app():
    # The API key in ?__pk_token must NOT reach the (untrusted) guest app.
    captured = {}

    def fake_proxy(vm_id, payload):
        captured["path"] = payload["path"]
        return _env(b"<html></html>")

    req = RequestFactory().get(
        f"/api/containers/15/preview/8000/?{PREVIEW_TOKEN_QUERY}=pk_x_y&keep=1"
    )
    build_preview_response(
        req, _container(), "8000", "", types.SimpleNamespace(proxy=fake_proxy)
    )
    assert "pk_x_y" not in captured["path"]
    assert PREVIEW_TOKEN_QUERY not in captured["path"]
    assert "keep=1" in captured["path"]  # the app's own params survive


def test_query_token_auth_sets_pathscoped_bootstrap_cookie():
    # After a query-param token hit, we drop a path-scoped HttpOnly cookie so the
    # embedded page's subresources (which carry no query string) authenticate too.
    req = RequestFactory().get(f"/api/containers/15/preview/8000/?{PREVIEW_TOKEN_QUERY}=pk_x_y")
    req._preview_query_token = "pk_x_y"  # set by PreviewTokenAuthentication
    resp = build_preview_response(
        req, _container(), "8000", "", _service(_env(b"<html></html>"))
    )
    cookie = resp.cookies[PREVIEW_TOKEN_COOKIE]
    assert cookie.value == "pk_x_y"
    assert cookie["path"] == "/api/containers/15/preview/8000/"
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"


def test_no_bootstrap_cookie_without_query_token():
    # Session-authed (IDE) hits have no query token → no cookie is set.
    req = RequestFactory().get("/api/containers/15/preview/8000/")
    resp = build_preview_response(
        req, _container(), "8000", "", _service(_env(b"<html></html>"))
    )
    assert PREVIEW_TOKEN_COOKIE not in resp.cookies
