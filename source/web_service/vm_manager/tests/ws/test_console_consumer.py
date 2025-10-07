import asyncio
import base64

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import re_path
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter

from vm_manager.console_consumers import ConsoleConsumer
from vm_manager.test_utils import create_user

pytestmark = pytest.mark.django_db


class FakeAuthMiddleware:
    """
    Minimal ASGI middleware that injects a given user into scope.
    """

    def __init__(self, app, user):
        self.app = app
        self.user = user

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = self.user
        return await self.app(scope, receive, send)


def build_app(user):
    route = [re_path(r"^ws/containers/(?P<pk>\d+)/$", ConsoleConsumer.as_asgi())]
    return FakeAuthMiddleware(URLRouter(route), user)


class FakeWS:
    def __init__(self, sid):
        self.sid = sid
        self.sent = []
        self.closed = False

    def __aiter__(self):
        # Keep pump alive with an endless async generator
        async def _gen():
            while True:
                await asyncio.sleep(3600)
                if False:
                    yield b""

        return _gen()

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def test_console_connect_anonymous_denied():
    app = build_app(AnonymousUser())

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/1/")
        connected, _ = await comm.connect()
        # Anonymous should be rejected
        assert connected is False

    asyncio.run(_main())


def test_console_connect_unauthorized_closes(monkeypatch):
    user = create_user(username="ws_unauth")

    # Force authorization failure
    async def fake_user_owns(pk, user_pk):
        return False

    monkeypatch.setattr(
        ConsoleConsumer, "_user_owns_container", staticmethod(fake_user_owns)
    )

    # Stub audit to avoid DB writes (and SQLite locks) during tests
    async def _noop_audit_ws(self, *args, **kwargs):
        return None

    monkeypatch.setattr(ConsoleConsumer, "audit_ws", _noop_audit_ws)
    app = build_app(user)

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/42/")
        connected, _ = await comm.connect()
        assert connected is False

    asyncio.run(_main())


def test_console_connect_send_broadcast_control_and_disconnect(monkeypatch):
    user = create_user(username="ws_ok")

    # Track fake upstreams per sid
    upstreams = {}

    async def fake_user_owns(pk, user_pk):
        return True

    async def fake_build_url_headers(self, pk):
        # Upstream URL and headers are not actually used by FakeWS
        return "ws://fake-upstream", {"Authorization": "Bearer t"}

    async def fake_open_upstream(self, upstream_url, headers):
        ws = FakeWS(self.sid)
        upstreams[self.sid] = ws
        self._upstream = ws
        return True

    monkeypatch.setattr(
        ConsoleConsumer, "_user_owns_container", staticmethod(fake_user_owns)
    )
    monkeypatch.setattr(
        ConsoleConsumer, "_build_upstream_url_and_headers", fake_build_url_headers
    )
    monkeypatch.setattr(ConsoleConsumer, "_open_upstream", fake_open_upstream)

    # Stub audit to avoid DB writes (and SQLite locks) during tests
    async def _noop_audit_ws(self, *args, **kwargs):
        return None

    monkeypatch.setattr(ConsoleConsumer, "audit_ws", _noop_audit_ws)
    app = build_app(user)

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/7/")
        connected, _ = await comm.connect()
        assert connected is True

        # Should receive initial text after connect
        msg = await comm.receive_from()
        assert msg == "[connected sid=s1]"
        assert "s1" in upstreams
        s1 = upstreams["s1"]

        # Send plain text to upstream and verify base64 payload
        await comm.send_to(text_data="pwd")
        await asyncio.sleep(0.05)
        assert s1.sent, "Upstream should have received data"
        decoded = base64.b64decode(s1.sent[-1]).decode("utf-8", errors="ignore")
        assert decoded == "pwd"

        # Disconnect: remaining upstream(s) should be closed (s1)
        await comm.disconnect()
        assert s1.closed is True

    asyncio.run(_main())
