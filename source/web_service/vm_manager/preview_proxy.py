"""Preview relay: forward a browser request to the VM app via the node proxy.

Replaces the old ``curl`` + base64→PNG + JS/CSS string-rewriting hack. The node
returns the upstream response binary-safe (real ``Content-Type``, verbatim
bytes), so images / ``openapi.json`` / fonts / source maps come back correct.

For HTML only we inject a ``<base>`` and re-root absolute paths so links and
assets stay inside the preview instead of escaping to the pequeroku origin
(e.g. a bare ``href="/"`` no longer lands on the landing page). JS/CSS bodies are
passed through untouched — rewriting their string literals is exactly what broke
ES modules and JSON before.
"""

import base64
import re

from django.http import HttpResponse
from rest_framework.authentication import SessionAuthentication


class CSRFExemptSessionAuthentication(SessionAuthentication):
    """Session auth without CSRF enforcement, for the preview proxy only.

    The previewed app's own forms POST through this endpoint and carry the
    *guest* app's CSRF token, never pequeroku's — so DRF's CSRF check would block
    every form. Skipping it here is safe: ``sessionid`` is ``SameSite=Lax``, so a
    cross-site POST never carries the session and thus can't be forged through
    this endpoint.
    """

    def enforce_csrf(self, request):  # noqa: D401 - intentional no-op
        return


# Request headers we forward upstream. Deliberately tiny: never leak pequeroku's
# session cookie or auth token into the previewed (untrusted) app.
_FORWARD_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "user-agent", "range"}
)

# Response headers we never relay back to the browser.
_DROP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",  # upstream was forced to identity
        "x-frame-options",  # frame-busting: we must be embeddable
        "content-security-policy",  # may carry frame-ancestors
        "set-cookie",  # v1: don't drop app cookies onto our origin
    }
)


def _header_value(headers, name: str):
    name = name.lower()
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _no_cache(resp):
    """Forbid caching of preview responses.

    A dev preview must always reflect the live app — and a single cached
    ``301`` from an old route (Django's APPEND_SLASH redirect) sticks in the
    browser permanently and keeps redirecting even after the server is fixed.
    ``no-store`` on every proxied response (pages, assets AND redirects) keeps
    the preview fresh and immune to that class of staleness.
    """
    resp["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    resp["Pragma"] = "no-cache"
    return resp


def _rewrite_html(html: str, prefix: str) -> str:
    """Inject ``<base>`` and re-root absolute paths under ``prefix`` (HTML only)."""

    def reroot(match: "re.Match[str]") -> str:
        return match.group(1) + prefix + match.group(2).lstrip("/")

    def fix_srcset(match: "re.Match[str]") -> str:
        items = []
        for part in match.group(2).split(","):
            tokens = part.strip().split()
            if not tokens:
                continue
            url = tokens[0]
            if url.startswith("/"):
                url = prefix + url.lstrip("/")
            items.append(" ".join([url, *tokens[1:]]))
        return match.group(1) + ", ".join(items) + match.group(3)

    # Drop any existing <base> (we set our own below).
    html = re.sub(r"(?is)<base[^>]*>", "", html)

    # Re-root absolute paths BEFORE injecting our <base> (otherwise the base's own
    # absolute href would get rewritten too -> doubled prefix). `/[^"\']*` matches
    # a bare "/" too — the case the old regex missed that sent it to the landing.
    html = re.sub(
        r'(?i)(\s(?:href|src|action|poster)\s*=\s*["\'])(/[^"\']*)',
        reroot,
        html,
    )
    html = re.sub(r'(?i)(\ssrcset\s*=\s*["\'])([^"\']+)(["\'])', fix_srcset, html)

    # Now inject exactly one <base href="{prefix}"> as the first child of <head>.
    if re.search(r"(?is)<head[^>]*>", html):
        html = re.sub(
            r"(?is)(<head[^>]*>)",
            lambda m: m.group(1) + f'<base href="{prefix}">',
            html,
            count=1,
        )
    else:
        html = f'<head><base href="{prefix}"></head>' + html

    return html


def _pick_request_headers(request) -> dict:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _FORWARD_REQUEST_HEADERS
    }


def _cookie_header(jar: dict) -> str:
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def _parse_set_cookie(raw: str):
    """Extract ``(name, value)`` from a Set-Cookie header (attributes ignored)."""
    first = raw.split(";", 1)[0].strip()
    if "=" not in first:
        return None, None
    name, _, value = first.partition("=")
    return name.strip(), value.strip()


def _update_cookie_jar(request, jar_key: str, jar: dict, up_headers) -> None:
    """Fold the app's Set-Cookie headers into the per-(container,port) session jar.

    The jar lives ONLY server-side (never relayed to the browser), so the guest
    app's ``sessionid``/``csrftoken`` can't collide with pequeroku's own cookies
    on the shared origin. This is what lets login + CSRF-protected forms work.
    """
    session = getattr(request, "session", None)
    if session is None:
        return
    changed = False
    for key, value in up_headers:
        if key.lower() != "set-cookie":
            continue
        name, val = _parse_set_cookie(value)
        if not name:
            continue
        if val == "":  # logout / deletion (e.g. sessionid=""; expires=1970)
            if jar.pop(name, None) is not None:
                changed = True
        elif jar.get(name) != val:
            jar[name] = val
            changed = True
    if changed:
        all_jars = dict(session.get("preview_cookies", {}))
        all_jars[jar_key] = jar
        session["preview_cookies"] = all_jars  # top-level set -> modified
        session.modified = True


def build_preview_response(request, container, port, path, service) -> HttpResponse:
    """Relay ``request`` to ``container``'s app on ``port`` and return the response."""
    query = request.META.get("QUERY_STRING", "")
    target = "/" + (path or "")
    if query:
        target = f"{target}?{query}"

    # Replay the guest app's own cookies from the server-side jar (never the
    # browser's cookies — those carry pequeroku's session and must not leak).
    session = getattr(request, "session", None)
    jar_key = f"{container.pk}:{port}"
    stored = session.get("preview_cookies", {}) if session is not None else {}
    jar = dict(stored.get(jar_key, {}))
    fwd_headers = _pick_request_headers(request)
    if jar:
        fwd_headers["Cookie"] = _cookie_header(jar)

    raw_body = request.body
    payload = {
        "target_port": int(port),
        "method": request.method,
        "path": target,
        "headers": fwd_headers,
        "body_b64": base64.b64encode(raw_body).decode("ascii") if raw_body else None,
        "timeout": 30,
    }

    try:
        env = service.proxy(str(container.container_id), payload)
    except Exception as exc:
        return _no_cache(
            HttpResponse(
                f"Preview proxy error: {exc}", status=502, content_type="text/plain"
            )
        )

    if not env or not env.get("ok", False):
        reason = (env or {}).get("reason") or "Preview not available"
        return _no_cache(
            HttpResponse(
                reason,
                status=int((env or {}).get("status", 502)),
                content_type="text/plain",
            )
        )

    up_headers = env.get("headers") or []
    _update_cookie_jar(request, jar_key, jar, up_headers)
    body_bytes = base64.b64decode(env.get("body_b64") or "")
    content_type = (
        _header_value(up_headers, "content-type") or "application/octet-stream"
    )
    prefix = f"/api/containers/{container.pk}/preview/{port}/"

    if "text/html" in content_type.lower():
        body_bytes = _rewrite_html(
            body_bytes.decode("utf-8", errors="replace"), prefix
        ).encode("utf-8")

    resp = HttpResponse(
        body_bytes, status=int(env.get("status", 200)), content_type=content_type
    )
    for key, value in up_headers:
        lkey = key.lower()
        if lkey in _DROP_RESPONSE_HEADERS or lkey == "content-type":
            continue
        if lkey == "location" and value.startswith("/"):
            value = prefix + value.lstrip("/")  # keep redirects inside the proxy
        resp[key] = value
    resp["X-Robots-Tag"] = "noindex"
    # Allow embedding: bypass XFrameOptionsMiddleware (which would add DENY).
    resp.xframe_options_exempt = True
    return _no_cache(resp)
