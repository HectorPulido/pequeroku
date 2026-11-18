"""Browser preview grants, scoped to a separate HTTPS origin per VM and port."""

import re
import secrets
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from pequeroku.live_access import current_session_user, vm_accessible

_TICKET_AGE = 60
_GRANT_AGE = 8 * 60 * 60
_COOKIE = "__Host-pequeroku-preview"
_HANDLE = re.compile(r"[A-Za-z0-9_-]{43}")


def is_preview_host(authority):
    suffix = settings.PREVIEW_HOST_SUFFIX
    if not suffix:
        return False
    host = authority.partition(":")[0].lower().rstrip(".")
    return host == suffix or host.endswith(f".{suffix}")


def preview_host_urls(get_response):
    def middleware(request):
        if is_preview_host(request.get_host()):
            request.urlconf = "vm_manager.preview_urls"
            request.COOKIES.pop(settings.SESSION_COOKIE_NAME, None)
            request.COOKIES.pop(settings.CSRF_COOKIE_NAME, None)
        elif request.method not in SAFE_METHODS:
            try:
                request_origin = urlsplit(request.headers.get("Origin", ""))
            except ValueError:
                return HttpResponseForbidden()
            if is_preview_host(request_origin.netloc):
                return HttpResponseForbidden()
        return get_response(request)

    return middleware


def preview_origin(pk, port):
    if not settings.PREVIEW_ORIGIN_TEMPLATE or not 1 <= port <= 65535:
        return None
    return settings.PREVIEW_ORIGIN_TEMPLATE.replace("{preview}", f"vm-{pk}-{port}")


def _preview_path(pk, port):
    return f"/api/containers/{pk}/preview/{port}/"


def _no_store(response):
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_http_methods(["GET", "HEAD"])
def launch_preview(request, pk, port, path=""):
    from .preview_proxy import _public_origin, _strip_preview_token

    if not vm_accessible(request.user, pk) or not request.session.session_key:
        raise Http404
    origin = preview_origin(pk, port)
    control_origin = _public_origin(request)
    if origin is None or not control_origin.startswith("https://"):
        return _no_store(
            HttpResponse("Configure an isolated HTTPS preview origin.", status=503)
        )

    if request.method == "HEAD":
        return _no_store(HttpResponse())

    prefix = _preview_path(pk, port)
    target = prefix + quote(path.lstrip("/"), safe="/")
    query = _strip_preview_token(request.META.get("QUERY_STRING", ""))
    if query:
        target = f"{target}?{query}"
    ticket = secrets.token_urlsafe(32)
    cache.set(
        f"preview-ticket:{ticket}",
        {
            "origin": origin,
            "control_origin": control_origin,
            "session_key": request.session.session_key,
            "user_id": request.user.pk,
            "pk": pk,
            "port": port,
            "target": target,
        },
        _TICKET_AGE,
    )
    nonce = secrets.token_urlsafe(24)
    response = HttpResponse(
        format_html(
            "<!doctype html><title>Open preview</title>"
            '<form method="post" action="{}"><input type="hidden" name="ticket" value="{}">'
            '<button type="submit">Open preview</button></form>'
            '<script nonce="{}">document.forms[0].submit()</script>',
            f"{origin}{prefix}.pequeroku-auth",
            ticket,
            nonce,
        )
    )
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; "
        f"form-action {origin}; frame-ancestors 'self'; base-uri 'none'"
    )
    response["X-Frame-Options"] = "SAMEORIGIN"
    _no_store(response)
    response["Referrer-Policy"] = "origin"
    return response


@require_POST
@csrf_exempt
def redeem_preview_ticket(request, pk, port):
    ticket = request.POST.get("ticket", "")
    if not _HANDLE.fullmatch(ticket):
        raise Http404
    origin = preview_origin(pk, port)
    record = cache.get(f"preview-ticket:{ticket}")
    if (
        origin is None
        or request.get_host() != urlsplit(origin).netloc
        or not record
        or record["origin"] != origin
        or record["control_origin"] != request.headers.get("Origin")
        or not cache.add(f"preview-redeemed:{ticket}", True, _TICKET_AGE)
    ):
        raise Http404
    user = current_session_user(record["session_key"], record["user_id"])
    if user is None or not vm_accessible(user, pk):
        raise Http404
    cache.delete(f"preview-ticket:{ticket}")

    grant = secrets.token_urlsafe(32)
    cache.set(f"preview-grant:{grant}", record, _GRANT_AGE)
    response = HttpResponseRedirect(record["target"], status=303)
    response.set_cookie(
        _COOKIE,
        grant,
        max_age=_GRANT_AGE,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return _no_store(response)


class PreviewBrowserAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if not is_preview_host(request.get_host()):
            return None
        grant = request.COOKIES.get(_COOKIE, "")
        if not _HANDLE.fullmatch(grant):
            return None
        record = cache.get(f"preview-grant:{grant}")
        if not record:
            return None
        kwargs = request.parser_context["kwargs"]
        if (
            str(record["pk"]) != str(kwargs["pk"])
            or str(record["port"]) != str(kwargs["port"])
            or request.get_host() != urlsplit(record["origin"]).netloc
        ):
            return None
        if (
            request.method not in SAFE_METHODS
            and request.headers.get("Origin") != record["origin"]
        ):
            raise PermissionDenied("Preview requests must come from the preview origin")
        user = current_session_user(record["session_key"], record["user_id"])
        if user is None:
            return None
        request._preview_grant = grant
        return user, record


async def preview_grant_is_live(grant):
    return await cache.aget(f"preview-grant:{grant}") is not None
