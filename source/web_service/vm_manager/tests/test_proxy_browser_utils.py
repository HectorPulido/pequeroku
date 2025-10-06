import base64
import pytest
from django.http import HttpResponse
from rest_framework.response import Response

from vm_manager.proxy_browser_utils import (
    ensure_trailing_slash,
    encode_url,
    rewrite_paths,
    parse_get,
)
from vm_manager.test_utils import create_container


pytestmark = pytest.mark.django_db


# --------------------------
# Helper: Fake VM service(s)
# --------------------------
class FakeVMServiceOK:
    """A fake service returning predefined stdout content without raising."""

    def __init__(self, stdout: str):
        self.stdout = stdout
        self.calls = []

    def execute_sh(self, container_id: str, cmd: str):
        # Record calls to assert command formatting if needed
        self.calls.append((container_id, cmd))
        return {"stdout": self.stdout}


class FakeVMServiceError:
    """A fake service that simulates an exception during command execution."""

    def execute_sh(self, container_id: str, cmd: str):
        raise RuntimeError("boom")


# --------------------------
# Tests for ensure_trailing_slash
# --------------------------
def test_ensure_trailing_slash_basic_cases():
    # Empty string stays empty
    assert ensure_trailing_slash("") == ""

    # Absolute path stays unchanged
    assert ensure_trailing_slash("/foo/bar") == "/foo/bar"

    # External schemes or protocol-relative stay unchanged
    assert ensure_trailing_slash("http://example.com") == "http://example.com"
    assert ensure_trailing_slash("https://example.com") == "https://example.com"
    assert ensure_trailing_slash("//cdn.example.com") == "//cdn.example.com"
    assert (
        ensure_trailing_slash("data:image/png;base64,xyz")
        == "data:image/png;base64,xyz"
    )
    assert (
        ensure_trailing_slash("mailto:someone@example.com")
        == "mailto:someone@example.com"
    )
    assert ensure_trailing_slash("tel:+1234567") == "tel:+1234567"
    assert ensure_trailing_slash("javascript:void(0)") == "javascript:void(0)"

    # Relative path gets a trailing slash appended
    assert ensure_trailing_slash("img.png") == "img.png/"

    # Query/hash suffix is not specially handled by logic; slash is appended at the end
    assert ensure_trailing_slash("file?x=1") == "file?x=1/"
    assert ensure_trailing_slash("file#frag") == "file#frag/"

    # Leading/trailing whitespace is stripped first
    assert ensure_trailing_slash("  mailto:x  ") == "mailto:x"


# --------------------------
# Tests for encode_url
# --------------------------
def test_encode_url_encodes_and_prefixes():
    # Encodes all unsafe chars (safe="") and strips the leading '/'
    out = encode_url("/a/b", "p/")
    assert out == "p/a%2Fb/"

    out2 = encode_url("   /a b  ", "/prefix/")
    # "a b" -> "a%20b"
    assert out2 == "/prefix/a%20b/"


# --------------------------
# Tests for rewrite_paths (HTML)
# --------------------------
def test_rewrite_paths_html_injects_base_and_rewrites_attributes():
    prefix = "/proxy/"
    html = (
        "<html><head><title>T</title></head>"
        "<body>"
        '<a href="/a/b">Link</a>'
        '<img src="img.png">'
        '<img srcset="/i/a.png 1x, img2.png 2x">'
        "</body></html>"
    )
    out = rewrite_paths(html, prefix, "index.html")

    # A single base tag injected right after <head>
    assert '<head><base href="/proxy/proxy%2F/">' in out

    # Absolute href rewritten to encoded + trailing slash
    assert "/proxy/a%2Fb/" in out

    # Relative src ensured to have trailing slash
    assert 'src="img.png/"' in out

    # srcset handling:
    # - Absolute entries rewritten with encode_url
    # - Relative entries ensured with trailing slash
    assert 'srcset="/proxy/i%2Fa.png/ 1x, img2.png/ 2x"' in out


def test_rewrite_paths_html_replaces_existing_base_once():
    prefix = "/p/"
    html = (
        "<html><head><base href='/old/'><title>x</title></head>"
        "<body><a href='/abs'>A</a></body></html>"
    )
    out = rewrite_paths(html, prefix, "page.html")

    # Old base removed, new base injected
    assert "href='/old/'" not in out
    assert '<head><base href="/p/p%2F/"><title>x</title></head>' in out

    # Absolute link got rewritten through encode_url
    # Absolute link got rewritten through encode_url - letters are not percent-encoded
    assert "/p/abs/" in out


def test_rewrite_paths_html_inserts_head_if_missing():
    prefix = "/p/"
    html = "<body><a href='/x'>x</a></body>"
    out = rewrite_paths(html, prefix, "nohead.html")

    # When no <head>, a minimal head with base is injected at the beginning
    assert out.startswith('<head><base href="/p/p%2F/"></head>')
    # And absolute attributes are still rewritten
    assert "/p/x/" in out


# --------------------------
# Tests for rewrite_paths (CSS)
# --------------------------
def test_rewrite_paths_css_url_and_import():
    prefix = "/assets/"
    css = 'body{background:url("/img/bg.png")} @import "/css/site.css";'
    out = rewrite_paths(css, prefix, "styles/main.css")

    # url("/abs") -> url("/prefix/a%2Fb%2Ec%2E..")
    # png => "bg%2Epng"
    assert 'url("/assets/img%2Fbg.png/")' in out
    assert '@import "/assets/css%2Fsite.css/"' in out

    # Relative url should remain untouched
    css_rel = 'div{background:url("rel/bg.png")}'
    out_rel = rewrite_paths(css_rel, prefix, "styles/app.css")
    assert out_rel == css_rel


# --------------------------
# Tests for rewrite_paths (JS)
# --------------------------
def test_rewrite_paths_js_string_literals():
    prefix = "/p/"
    js = 'const a="/api/v1"; const b="rel.js"; const c=\' /space/abs\';'
    out = rewrite_paths(js, prefix, "app.js")

    # Absolute string literal is rewritten
    assert 'const a="/p/api%2Fv1/";' in out
    # Relative string remains unchanged
    assert 'const b="rel.js";' in out
    # Leading space is ignored then encoded
    assert "const c='/p/space%2Fabs/';" in out


# --------------------------
# Tests for parse_get
# --------------------------
def test_parse_get_returns_png_when_base64():
    container = create_container()
    data = b"fake-bytes"
    b64 = base64.b64encode(data).decode("ascii")
    service = FakeVMServiceOK(b64)

    resp = parse_get(
        port=8080,
        path="image.png",
        container=container,
        base_url="/proxy/",
        service=service,
    )

    # Should pick the "image" path (base64 decode) and send back PNG content
    assert isinstance(resp, HttpResponse)
    assert resp["Content-Type"] == "image/png"
    assert resp.content == data


def test_parse_get_rewrites_html_response_default_content_type():
    container = create_container()
    # Return a small HTML that will be path-rewritten
    html = '<html><head></head><body><a href="/abs">A</a><img src="rel.png">á</body></html>'
    service = FakeVMServiceOK(html)

    resp = parse_get(
        port=8081,
        path="index.html",
        container=container,
        base_url="/proxy/",
        service=service,
    )

    assert isinstance(resp, HttpResponse)
    # No explicit content type for .html by this function
    assert resp.get("Content-Type") in (
        None,
        "",
        "text/html; charset=utf-8",
    )  # Django may default this
    body = resp.content.decode("utf-8")
    assert '<base href="/proxy/proxy%2F/">' in body
    assert "/proxy/abs/" in body
    assert 'src="rel.png/"' in body


def test_parse_get_css_sets_content_type_and_rewrites_urls():
    container = create_container()
    css = 'body{background:url("/a.png")}'
    service = FakeVMServiceOK(css)

    resp = parse_get(
        port=8082,
        path="main.css",
        container=container,
        base_url="/p/",
        service=service,
    )

    assert isinstance(resp, HttpResponse)
    assert resp["Content-Type"] == "text/css"
    assert 'url("/p/a.png/")' in resp.content.decode("utf-8")


def test_parse_get_js_sets_content_type_and_rewrites_literals():
    container = create_container()
    js = 'const p="/x"; const r="rel";'
    service = FakeVMServiceOK(js)

    resp = parse_get(
        port=8083,
        path="app.js",
        container=container,
        base_url="/p/",
        service=service,
    )

    assert isinstance(resp, HttpResponse)
    assert resp["Content-Type"] == "application/javascript"
    assert 'const p="/p/x/";' in resp.content.decode("utf-8")
    assert 'const r="rel";' in resp.content.decode("utf-8")


def test_parse_get_returns_404_when_too_small():
    container = create_container()
    # stdout shorter than 5 chars returns 404
    service = FakeVMServiceOK("1234")

    resp = parse_get(
        port=8084,
        path="something",
        container=container,
        base_url="/p/",
        service=service,
    )

    assert isinstance(resp, Response)
    assert resp.status_code == 404


def test_parse_get_returns_400_when_service_errors():
    container = create_container()
    service = FakeVMServiceError()

    resp = parse_get(
        port=8085,
        path="anything",
        container=container,
        base_url="/p/",
        service=service,
    )

    assert isinstance(resp, Response)
    assert resp.status_code == 400
    assert "Something went wrong" in str(resp.data)
