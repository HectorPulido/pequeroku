import base64
import types

from django.test import RequestFactory

from vm_manager.preview_proxy import (
    CSRFExemptSessionAuthentication,
    _rewrite_html,
    build_preview_response,
)


def test_csrf_exempt_session_auth_skips_enforcement():
    # enforce_csrf is a no-op (returns None) so previewed-app form POSTs aren't
    # blocked by pequeroku's CSRF check.
    assert CSRFExemptSessionAuthentication().enforce_csrf(None) is None


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
    out = _rewrite_html(html, prefix)

    assert f'<base href="{prefix}">' in out
    assert f'href="{prefix}"' in out  # bare "/" re-rooted (the old bug)
    assert f'href="{prefix}about"' in out
    assert f'src="{prefix}static/logo.png"' in out
    assert 'href="rel/page"' in out  # relative untouched; <base> resolves it


def test_rewrite_html_injects_runtime_shim():
    out = _rewrite_html(
        "<html><head></head><body></body></html>",
        "/api/containers/15/preview/8000/",
    )
    assert '<base href="/api/containers/15/preview/8000/">' in out
    # Shim runs as a script; PREFIX has NO trailing slash so PREFIX + "/posts" works.
    assert 'var PREFIX="/api/containers/15/preview/8000"' in out
    assert "window.fetch=" in out  # API edge patched
    assert "Element.prototype.setAttribute" in out  # img/href setters patched


def test_rewrite_html_inserts_head_when_missing():
    out = _rewrite_html("<body><a href='/x'>x</a></body>", "/p/")
    # A <head> is synthesized, starting with our <base> (the shim follows it).
    assert '<head><base href="/p/"><script>' in out
    assert "</head><body>" in out


def test_rewrite_html_srcset_absolute_entries():
    out = _rewrite_html('<img srcset="/a.png 1x, /b.png 2x">', "/p/")
    assert "/p/a.png 1x" in out
    assert "/p/b.png 2x" in out


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
