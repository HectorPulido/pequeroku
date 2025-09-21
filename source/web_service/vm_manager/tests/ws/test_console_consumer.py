import asyncio
import json
import types

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
        # No upstream traffic by default
        async def _gen():
            if False:
                yield None

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

    async def fake_open_upstream(self, sid, upstream_url, headers):
        ws = FakeWS(sid)
        upstreams[sid] = ws
        return ws

    async def fake_start_reader(self, sid):
        # No-op to avoid background tasks for tests
        return None

    monkeypatch.setattr(
        ConsoleConsumer, "_user_owns_container", staticmethod(fake_user_owns)
    )
    monkeypatch.setattr(
        ConsoleConsumer, "_build_upstream_url_and_headers", fake_build_url_headers
    )
    monkeypatch.setattr(ConsoleConsumer, "_open_upstream", fake_open_upstream)
    monkeypatch.setattr(ConsoleConsumer, "_start_reader", fake_start_reader)

    # Stub audit to avoid DB writes (and SQLite locks) during tests
    async def _noop_audit_ws(self, *args, **kwargs):
        return None

    monkeypatch.setattr(ConsoleConsumer, "audit_ws", _noop_audit_ws)
    app = build_app(user)

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/7/")
        connected, _ = await comm.connect()
        assert connected is True

        # Should receive initial info after connect
        data = await comm.receive_json_from()
        assert data["type"] == "info"
        assert data["message"] == "Connected"
        assert data["sessions"] == ["s1"]
        assert data["active"] == "s1"
        assert "s1" in upstreams
        s1 = upstreams["s1"]

        # Send plain text to active session
        await comm.send_to(text_data="pwd")
        await asyncio.sleep(0.05)
        # ends with \n internally
        assert s1.sent and s1.sent[-1].endswith("\n")
        assert s1.sent[-1].strip() == "pwd"

        # Broadcast command to all sessions (only s1 currently)
        await comm.send_to(text_data=json.dumps({"data": "ls", "broadcast": True}))
        await asyncio.sleep(0.05)
        assert s1.sent[-1].strip() == "ls"

        # Open second session s2
        await comm.send_to(text_data=json.dumps({"control": "open", "sid": "s2"}))
        evt = await comm.receive_json_from()
        assert evt["type"] == "info"
        assert evt["message"] == "session-opened"
        assert evt["sid"] == "s2"
        assert evt["active"] == "s2"
        assert "s2" in upstreams
        s2 = upstreams["s2"]
        assert s2.closed is False

        # Focus back to s1
        await comm.send_to(text_data=json.dumps({"control": "focus", "sid": "s1"}))
        evt = await comm.receive_json_from()
        assert evt["type"] == "info"
        assert evt["message"] == "session-focused"
        assert evt["sid"] == "s1"

        # Sending plain text now should hit s1 (not s2)
        prev_s2_count = len(s2.sent)
        await comm.send_to(text_data="date")
        await asyncio.sleep(0.05)
        assert s1.sent[-1].strip() == "date"
        assert len(s2.sent) == prev_s2_count

        # Close s2
        await comm.send_to(text_data=json.dumps({"control": "close", "sid": "s2"}))
        evt = await comm.receive_json_from()
        assert evt["type"] == "info"
        assert evt["message"] == "session-closed"
        assert evt["sid"] == "s2"
        assert s2.closed is True

        # Disconnect: remaining upstream(s) should be closed (s1)
        await comm.disconnect()
        assert s1.closed is True

    asyncio.run(_main())
