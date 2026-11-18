from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import Client
from django.urls import re_path
import pytest

from pequeroku import ws_access
from vm_manager.test_utils import create_container, create_node, create_user


class EchoConsumer(AsyncWebsocketConsumer):
    async def receive(self, text_data=None, bytes_data=None):
        await self.send(text_data=text_data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "origin", "allowed"),
    [
        ("panel.test", "https://panel.test", True),
        ("panel.test", "https://vm-1-80.preview.test", False),
        ("vm-1-80.preview.test", "https://vm-1-80.preview.test", False),
        ("panel.test", "", False),
    ],
)
async def test_websocket_only_accepts_its_panel_origin(settings, host, origin, allowed):
    settings.PREVIEW_HOST_SUFFIX = "preview.test"

    async def accept(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        await receive()

    app = ws_access.require_control_origin(accept)
    socket = WebsocketCommunicator(
        app, "/ws/", headers=[(b"host", host.encode()), (b"origin", origin.encode())]
    )
    try:
        connected, _ = await socket.connect()
        assert connected is allowed
    finally:
        await socket.disconnect()


@database_sync_to_async
def _connect_data():
    owner = create_user("ws-owner")
    collaborator = create_user("ws-collaborator")
    container = create_container(user=owner, node=create_node())
    container.allowed_users.add(collaborator)
    client = Client()
    client.force_login(collaborator)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME]
    return container, collaborator, client, cookie.output(header="").strip().encode()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("revoke_session", [False, True])
async def test_socket_closes_when_access_is_revoked(monkeypatch, revoke_session):
    monkeypatch.setattr(ws_access, "_RECHECK_SECONDS", 0.05)
    container, user, client, cookie = await _connect_data()
    app = AuthMiddlewareStack(
        URLRouter(
            [
                re_path(
                    r"^vm/(?P<pk>\d+)/$",
                    ws_access.require_live_container_access(EchoConsumer.as_asgi()),
                )
            ]
        )
    )
    socket = WebsocketCommunicator(
        app, f"/vm/{container.pk}/", headers=[(b"cookie", cookie)]
    )
    try:
        assert (await socket.connect())[0]
        await socket.send_to(text_data="allowed")
        assert await socket.receive_from() == "allowed"
        if revoke_session:
            await database_sync_to_async(client.logout)()
        else:
            await database_sync_to_async(container.allowed_users.remove)(user)
            await socket.send_to(text_data="denied")
        assert await socket.receive_output() == {
            "type": "websocket.close",
            "code": 4403,
        }
    finally:
        await socket.disconnect()
