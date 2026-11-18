"""Recheck the session and VM access while a WebSocket is open."""

import asyncio
from time import monotonic
from urllib.parse import urlsplit

from django.db import DatabaseError

from .live_access import session_can_access_vm
from vm_manager.preview_access import is_preview_host

_RECHECK_SECONDS = 2
_ACCESS_DENIED = 4403


def require_control_origin(app):
    async def application(scope, receive, send):
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin-1").lower()
        try:
            origin = urlsplit(headers.get(b"origin", b"").decode("latin-1"))
            allowed = (
                origin.scheme in {"http", "https"}
                and origin.netloc.lower() == host
                and not is_preview_host(host)
            )
        except ValueError:
            allowed = False
        if not allowed:
            await receive()
            await send({"type": "websocket.close", "code": _ACCESS_DENIED})
            return
        await app(scope, receive, send)

    return application


def require_live_container_access(app):
    async def application(scope, receive, send):
        session_key = scope["session"].session_key
        user_id = scope["user"].pk
        vm_id = scope["url_route"]["kwargs"]["pk"]
        lock = asyncio.Lock()
        valid_until = 0.0
        revoked = False

        async def authorized(*, fresh=False):
            nonlocal valid_until, revoked
            async with lock:
                if revoked:
                    return False
                if not fresh and monotonic() < valid_until:
                    return True
                try:
                    if await session_can_access_vm(session_key, user_id, vm_id):
                        valid_until = monotonic() + _RECHECK_SECONDS
                        return True
                except DatabaseError:
                    pass
                revoked = True
                await send({"type": "websocket.close", "code": _ACCESS_DENIED})
                return False

        async def guarded_receive():
            while not revoked:
                try:
                    event = await asyncio.wait_for(receive(), timeout=_RECHECK_SECONDS)
                except TimeoutError:
                    if not await authorized():
                        break
                    continue
                if event["type"] != "websocket.receive" or await authorized(fresh=True):
                    return event
                break
            return {"type": "websocket.disconnect", "code": _ACCESS_DENIED}

        async def guarded_send(event):
            if event["type"] in ("websocket.accept", "websocket.send"):
                if not await authorized():
                    return
            if not revoked:
                await send(event)

        scope = {**scope, "check_vm_access": authorized}
        await app(scope, guarded_receive, guarded_send)

    return application
