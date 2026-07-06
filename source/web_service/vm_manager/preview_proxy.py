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
from urllib.parse import parse_qsl, urlencode

import httpx
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import authentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.renderers import BaseRenderer


class PreviewPassthroughRenderer(BaseRenderer):
    """Accept ANY media type so DRF content negotiation never 406s the preview.

    The previewed app speaks for itself (HTML, JSON, octet-stream, and crucially
    ``text/event-stream`` for Gradio's SSE queue). DRF's default renderers don't
    advertise those media types, so a request that sends e.g.
    ``Accept: text/event-stream`` with NO ``*/*`` fallback is rejected with 406
    *before* our proxy view even runs. A wildcard ``media_type`` makes every
    Accept satisfiable; the view returns a raw ``HttpResponse`` so ``render`` is
    never actually invoked.
    """

    media_type = "*/*"
    format = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


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


# Preview token auth: agents (and browser embeds that can't set request headers)
# present their platform API key to the SAME preview URL the IDE uses. It travels
# as ``Authorization: Bearer pk_...``, the ``__pk_token`` query param, or the
# short-lived ``__pk_preview_token`` cookie we set after a query-param hit so an
# embedded page's subresources authenticate too. The query param is namespaced
# (``__pk_``) so it won't collide with the guest app's own params, and it is
# STRIPPED before the request is forwarded upstream (the guest app must never see
# the key). Header/cookie tokens are never forwarded either (see the header
# allowlist / server-side cookie jar).
PREVIEW_TOKEN_QUERY = "__pk_token"
PREVIEW_TOKEN_COOKIE = "__pk_preview_token"
PREVIEW_TOKEN_TTL = 3600  # seconds the bootstrap cookie stays valid


class PreviewTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate the preview with a platform API key (header / query / cookie).

    Registered BEFORE session auth on the preview view so scripts and agents can
    reach the preview without a login cookie. Any failure returns ``None`` (it
    never raises) so DRF falls through to session auth — the IDE keeps working and
    a bad/expired token just yields a clean 401. Ownership is still enforced by the
    view's ``get_object()``: the key owner only ever sees their own containers.
    """

    def authenticate(self, request):
        raw, via = self._extract(request)
        if not raw:
            return None
        # Lazy import: platform_api imports vm_manager, so importing it at module
        # load could race Django's app registry.
        from platform_api.models import APIKey

        key = self._verify(APIKey, raw)
        if key is None or not key.has_scope(APIKey.SCOPE_READ):
            return None
        if via == "query":
            # Flag it so the view drops a path-scoped cookie for the subresources
            # (which load via the injected <base> and carry no query string).
            request._preview_query_token = raw
        return (key.user, key)

    def authenticate_header(self, request):
        return "Bearer"

    @staticmethod
    def _extract(request):
        parts = authentication.get_authorization_header(request).split()
        if len(parts) == 2 and parts[0].lower() == b"bearer":
            token = parts[1].decode("latin-1")
            if token.startswith("pk_"):
                return token, "header"
        params = getattr(request, "query_params", None)
        if params is None:
            params = request.GET
        query_token = params.get(PREVIEW_TOKEN_QUERY)
        if query_token and query_token.startswith("pk_"):
            return query_token, "query"
        cookie_token = request.COOKIES.get(PREVIEW_TOKEN_COOKIE)
        if cookie_token and cookie_token.startswith("pk_"):
            return cookie_token, "cookie"
        return None, None

    @staticmethod
    def _verify(api_key_model, raw):
        prefix, _, secret = raw[3:].partition("_")
        if not prefix or not secret:
            return None
        try:
            key = api_key_model.objects.select_related("user").get(
                prefix=prefix, revoked=False
            )
        except api_key_model.DoesNotExist:
            return None
        if not key.verify_secret(secret) or not key.user.is_active:
            return None
        return key


def _strip_preview_token(query: str) -> str:
    """Drop the preview auth token from a query string before forwarding upstream.

    The guest app is untrusted; it must never receive the platform API key that
    the browser put in the URL. Only our namespaced param is removed, so the app's
    own query params pass through untouched.
    """
    if not query or PREVIEW_TOKEN_QUERY not in query:
        return query
    kept = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key != PREVIEW_TOKEN_QUERY
    ]
    return urlencode(kept)


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


# Runtime shim injected at the top of <head>, before any app script. The static
# HTML rewrite (and <base>) only fix markup that exists at parse time; this patches
# the browser APIs so absolute URLs the app builds AT RUNTIME in JS get re-rooted
# into the preview prefix too — the case <base> can't reach. We patch the API edge
# (fetch/XHR/WS, the src/href setters, setAttribute, innerHTML), NOT the app's source.
# Relative URLs are left alone (they already resolve via <base>). __PREFIX__ has no
# trailing slash. Known gaps: location.href= navigations, SPA pushState routing,
# CSS url(), and worker-scope fetches.
_SHIM_JS = """
(function(){
"use strict";
var PREFIX="__PREFIX__",PORT="__PORT__",ORIGIN=location.origin;
// Upstream self-origins. Frameworks like Gradio bake their OWN address
// (http://127.0.0.1:PORT/...) into runtime URLs; from the browser that resolves
// to the *user's* localhost -> ERR_CONNECTION_REFUSED. Collapse them to a path.
var SELF=["//127.0.0.1:"+PORT,"//localhost:"+PORT,"//0.0.0.0:"+PORT];
function stripSelf(u){
  var s=u,p=s.indexOf("://");
  if(p>0&&p<8)s="//"+s.slice(p+3);
  for(var i=0;i<SELF.length;i++){if(s.slice(0,SELF[i].length)===SELF[i])return s.slice(SELF[i].length)||"/";}
  return u;
}
function rw(u){
  if(typeof u!=="string"||!u)return u;
  var s=stripSelf(u);
  if(s.slice(0,ORIGIN.length+1)===ORIGIN+"/")s=s.slice(ORIGIN.length);
  else if(s===ORIGIN)s="/";
  if(s.charCodeAt(0)===47&&s.charCodeAt(1)!==47&&s.slice(0,PREFIX.length+1)!==PREFIX+"/"&&s!==PREFIX)return PREFIX+s;
  return s===u?u:s;
}
function rwSrcset(v){
  if(typeof v!=="string")return v;
  return v.split(",").map(function(p){var t=p.trim().split(/\\s+/);if(t[0])t[0]=rw(t[0]);return t.join(" ");}).join(", ");
}
function rwWs(u){
  if(typeof u!=="string")return u;
  var s=stripSelf(u);
  if(s.charCodeAt(0)===47&&s.charCodeAt(1)!==47){var pfx=(s.slice(0,PREFIX.length+1)===PREFIX+"/"||s===PREFIX)?"":PREFIX;return (location.protocol==="https:"?"wss://":"ws://")+location.host+pfx+s;}
  return s===u?u:s;
}
function rwHtml(h){
  if(typeof h!=="string")return h;
  return h.replace(/(\\s(?:src|href|action|poster|formaction)\\s*=\\s*["'])(\\/[^"']*)/gi,function(m,a,p){return a+rw(p);});
}
if(window.fetch){var of=window.fetch;window.fetch=function(i,init){try{if(typeof i==="string")i=rw(i);else if(i&&i.url)i=new Request(rw(i.url),i);}catch(e){}return of.call(this,i,init);};}
var xo=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(){try{if(arguments.length>1)arguments[1]=rw(arguments[1]);}catch(e){}return xo.apply(this,arguments);};
function wrapCtor(name,fn){var C=window[name];if(!C)return;function W(u,p){return p===undefined?new C(fn(u)):new C(fn(u),p);}W.prototype=C.prototype;["CONNECTING","OPEN","CLOSING","CLOSED"].forEach(function(k){if(k in C)W[k]=C[k];});try{window[name]=W;}catch(e){}}
wrapCtor("WebSocket",rwWs);wrapCtor("EventSource",rw);
var URLATTR={src:1,href:1,action:1,poster:1,formaction:1,data:1};
var sa=Element.prototype.setAttribute;Element.prototype.setAttribute=function(n,v){try{var k=(""+n).toLowerCase();if(k==="srcset")v=rwSrcset(v);else if(URLATTR[k])v=rw(v);}catch(e){}return sa.call(this,n,v);};
function patch(proto,prop,fn){if(!proto)return;var d=Object.getOwnPropertyDescriptor(proto,prop);if(!d||!d.set)return;Object.defineProperty(proto,prop,{configurable:true,enumerable:d.enumerable,get:d.get,set:function(v){try{v=fn(v);}catch(e){}d.set.call(this,v);}});}
[["HTMLImageElement","src"],["HTMLImageElement","srcset"],["HTMLScriptElement","src"],["HTMLLinkElement","href"],["HTMLAnchorElement","href"],["HTMLIFrameElement","src"],["HTMLSourceElement","src"],["HTMLSourceElement","srcset"],["HTMLMediaElement","src"],["HTMLFormElement","action"],["HTMLTrackElement","src"]].forEach(function(e){var c=window[e[0]];if(c)patch(c.prototype,e[1],e[1]==="srcset"?rwSrcset:rw);});
patch(Element.prototype,"innerHTML",rwHtml);patch(Element.prototype,"outerHTML",rwHtml);
var iah=Element.prototype.insertAdjacentHTML;if(iah)Element.prototype.insertAdjacentHTML=function(pos,h){return iah.call(this,pos,rwHtml(h));};
})();
"""


def _preview_shim(prefix: str, port) -> str:
    body = _SHIM_JS.replace("__PREFIX__", prefix.rstrip("/")).replace(
        "__PORT__", str(port)
    )
    return "<script>" + body + "</script>"


def _reroot_self_origin(text: str, replacement: str, port) -> str:
    """Collapse the upstream app's own absolute origin onto the preview base.

    Frameworks like Gradio bake their *own* address into asset URLs and the
    embedded JS config root (e.g. ``http://127.0.0.1:7860/theme.css``). The
    browser would resolve those against ITS OWN localhost
    (``ERR_CONNECTION_REFUSED``), so rewrite ``http(s)://`` and protocol-relative
    forms on 127.0.0.1 / localhost / 0.0.0.0 at the known target port to the
    preview base. ``replacement`` MUST be an absolute URL (scheme + host): Gradio
    does ``new URL(config.root)``, which throws "Invalid URL" on a bare path.
    A lambda sidesteps ``re.sub`` backreference interpretation in the URL.
    """
    pattern = re.compile(
        r"(?i)(?:https?:)?//(?:127\.0\.0\.1|localhost|0\.0\.0\.0):" + str(int(port))
    )
    return pattern.sub(lambda _m: replacement, text)


def _credential_manifest(html: str) -> str:
    """Make ``<link rel="manifest">`` fetch with credentials.

    Browsers fetch the web-app manifest WITHOUT cookies by default, so our
    session-authenticated preview endpoint 403s it. ``use-credentials`` makes the
    browser send the same-origin session cookie so the fetch succeeds.
    """

    def add_cred(match: "re.Match[str]") -> str:
        tag = match.group(0)
        if re.search(r"(?i)crossorigin", tag):
            return tag
        stripped = tag.rstrip()
        if stripped.endswith("/>"):
            return stripped[:-2] + ' crossorigin="use-credentials"/>'
        return stripped[:-1] + ' crossorigin="use-credentials">'

    return re.sub(
        r'(?i)<link\b[^>]*\brel\s*=\s*["\']?manifest["\']?[^>]*>', add_cred, html
    )


def _rewrite_html(html: str, prefix: str, port, origin: str = "") -> str:
    """Inject ``<base>`` + runtime shim and re-root absolute paths (HTML only)."""

    def reroot(match: "re.Match[str]") -> str:
        path = match.group(2)
        if path.startswith(prefix):  # already re-rooted -> don't double-prefix
            return match.group(0)
        return match.group(1) + prefix + path.lstrip("/")

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

    # Collapse the upstream's own absolute origin (host:port it baked into asset
    # URLs and its inline JS config, e.g. Gradio's ``root``) onto the preview base.
    # Runs over the WHOLE body so the embedded config JSON is fixed too, not just
    # attrs. Target is absolute (origin + prefix) so Gradio's new URL(root) works;
    # bare prefix is only a fallback when the caller omits the origin.
    self_origin_target = (
        origin.rstrip("/") + prefix.rstrip("/") if origin else prefix.rstrip("/")
    )
    html = _reroot_self_origin(html, self_origin_target, port)

    # Let the web-app manifest fetch carry our session cookie (else it 403s).
    html = _credential_manifest(html)

    # Inject <base> + the runtime shim as the first children of <head>, before any
    # app script runs (the shim must patch fetch/XHR/setters before app code uses them).
    injection = f'<base href="{prefix}">' + _preview_shim(prefix, port)
    if re.search(r"(?is)<head[^>]*>", html):
        html = re.sub(
            r"(?is)(<head[^>]*>)",
            lambda m: m.group(1) + injection,
            html,
            count=1,
        )
    else:
        html = f"<head>{injection}</head>" + html

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


def _forward_payload(request, container, port, path):
    """Build the node proxy payload + return the per-(container,port) cookie jar.

    Shared by the buffered and streaming paths: assembles the target (path+query),
    forwards the minimal request headers, and replays the guest app's OWN cookies
    from the server-side jar (never the browser's cookies — those carry
    pequeroku's session and must not leak into the previewed app).
    """
    query = _strip_preview_token(request.META.get("QUERY_STRING", ""))
    target = "/" + (path or "")
    if query:
        target = f"{target}?{query}"

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
    return payload, jar_key, jar


def _is_sse_request(request) -> bool:
    """True when the browser is asking for a Server-Sent Events stream."""
    return "text/event-stream" in request.headers.get("Accept", "").lower()


def _public_origin(request) -> str:
    """Best-effort public ``scheme://host`` the *browser* actually used.

    Behind Cloudflare → nginx the local hops can be plain http, so trusting
    ``request.scheme`` (or an ``X-Forwarded-Proto`` that nginx clobbered with its
    own ``$scheme``) yields ``http://`` — and the previewed app's rewritten asset
    URLs then get blocked as **mixed content** on the https page. Prefer explicit
    upstream signals, most-trustworthy first: Cloudflare's ``CF-Visitor`` JSON
    (which nginx leaves untouched), then ``X-Forwarded-Proto``, then the local
    scheme as a last resort.
    """
    proto = ""
    cf_visitor = request.META.get("HTTP_CF_VISITOR", "").replace(" ", "")
    if '"scheme":"https"' in cf_visitor:
        proto = "https"
    elif '"scheme":"http"' in cf_visitor:
        proto = "http"
    if not proto:
        proto = (request.META.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[0].strip()
    return f"{proto or request.scheme}://{request.get_host()}"


def _streaming_preview_response(request, container, port, path, service):
    """Relay an SSE/streamed response from the VM app to the browser, live.

    The DRF view stays SYNC (auth/get_object/cookie-jar untouched); this just
    returns a ``StreamingHttpResponse`` whose async generator drives httpx
    *inside the ASGI event loop*, so no worker thread is blocked per stream. We
    commit ``text/event-stream`` up front (the request asked for it) — we can't
    backfill the upstream status/headers once streaming has begun.
    """
    payload, _jar_key, _jar = _forward_payload(request, container, port, path)
    payload["headers"]["Accept"] = "text/event-stream"
    url, node_headers = service.stream_endpoint(str(container.container_id))

    async def relay():
        # connect timeout bounded; read timeout disabled so the stream can idle.
        timeout = httpx.Timeout(15.0, read=None)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=node_headers
                ) as upstream:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
        except Exception:
            # End the stream; the browser's EventSource will retry/surface it.
            return

    resp = StreamingHttpResponse(relay(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # stop nginx from buffering the SSE stream
    resp.xframe_options_exempt = True
    return resp


def build_preview_response(request, container, port, path, service) -> HttpResponse:
    """Relay ``request`` to ``container``'s app on ``port`` and return the response."""
    # SSE (AI chatbots, Gradio's queue) must stream, not buffer — route it to the
    # streaming proxy. Everything else (HTML, assets, JSON, redirects) is buffered.
    if _is_sse_request(request):
        return _streaming_preview_response(request, container, port, path, service)

    payload, jar_key, jar = _forward_payload(request, container, port, path)

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
        # Absolute base for re-rooting the app's self-origin — MUST be https on an
        # https page or the rewritten asset URLs get blocked as mixed content.
        origin = _public_origin(request)
        body_bytes = _rewrite_html(
            body_bytes.decode("utf-8", errors="replace"), prefix, port, origin
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
    _bootstrap_preview_cookie(request, resp, prefix)
    return _no_cache(resp)


def _bootstrap_preview_cookie(request, resp, prefix: str) -> None:
    """Drop a short-lived, path-scoped cookie after a query-param token auth.

    A page reached with ``?__pk_token=`` loads its assets via the injected
    ``<base>`` (no query string), so those subresource requests would be
    unauthenticated. Setting the token as an ``HttpOnly`` cookie scoped to this
    exact preview path lets them authenticate too — without ever leaking the key
    into the URL of every asset. The cookie stays server-visible only (it is never
    forwarded to the guest app, which uses the server-side cookie jar).
    """
    token = getattr(request, "_preview_query_token", None)
    if not token:
        return
    secure = _public_origin(request).lower().startswith("https")
    resp.set_cookie(
        PREVIEW_TOKEN_COOKIE,
        token,
        max_age=PREVIEW_TOKEN_TTL,
        path=prefix,
        httponly=True,
        samesite="Lax",
        secure=secure,
    )
