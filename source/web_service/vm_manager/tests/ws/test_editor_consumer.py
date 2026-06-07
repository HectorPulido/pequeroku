"""WebSocket tests for EditorConsumer.

Drives the consumer through a ``WebsocketCommunicator`` with a fake auth
middleware (injecting a user), a fake VM client (so no SSH/HTTP), and stubbed
revision store + audit (so no redis/DB writes during the handler bodies).
"""

import asyncio
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError
from django.urls import re_path
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter

from vm_manager.editor_consumers import EditorConsumer
from vm_manager.test_utils import create_user

pytestmark = pytest.mark.django_db


class FakeAuthMiddleware:
    def __init__(self, app, user):
        self.app = app
        self.user = user

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = self.user
        return await self.app(scope, receive, send)


def build_app(user):
    route = [re_path(r"^ws/containers/(?P<pk>\d+)/fs/$", EditorConsumer.as_asgi())]
    return FakeAuthMiddleware(URLRouter(route), user)


class FakeVMClient:
    """Records calls and returns canned VM responses."""

    def __init__(self):
        self.calls = []

    def list_dirs(self, cid, paths):
        self.calls.append(("list_dirs", paths))
        return [{"path": "/app/a.py", "name": "a.py", "path_type": "file"}]

    def read_file(self, cid, path):
        self.calls.append(("read_file", path))
        return {"name": "a.py", "content": "print(1)", "length": 8, "found": True}

    def create_dir(self, cid, path):
        self.calls.append(("create_dir", path))
        return {"ok": True}

    def upload_files(self, cid, payload):
        self.calls.append(("upload_files", payload))
        return {"ok": True}

    def execute_sh(self, cid, cmd, timeout=None):
        self.calls.append(("execute_sh", cmd))
        return {"ok": True, "stdout": "", "stderr": ""}

    def search(self, cid, req):
        self.calls.append(("search", req))
        return [{"path": "/app/a.py", "matchs": ["print(1)"]}]


_MISSING = object()  # sentinel: simulate a container that does not exist


def _patch_consumer(
    monkeypatch, *, owns=True, owns_error=False, vm_client=None, container=_MISSING
):
    # Resolve the container the consumer will "find". Default: a fake namespace.
    # Mock _get_container_with_node too so NO real DB read happens in a worker
    # thread (which would deadlock against the test's SQLite transaction lock).
    if container is _MISSING:
        container = SimpleNamespace(container_id="vm-ed-1", node=object())

    async def fake_owns(pk, user_pk):
        if owns_error:
            raise DatabaseError("db down")
        return owns

    async def fake_get_container(pk, use_select_related=False):
        if container is None:
            return None, None
        return container, getattr(container, "node", None)

    async def fake_service(self, container):
        return vm_client

    async def noop_first_start(self):
        return None

    async def noop_audit(self, *a, **k):
        return None

    async def fake_get_rev(self, cid, path):
        return 5

    async def fake_bump_rev(self, cid, path):
        return 6

    monkeypatch.setattr(EditorConsumer, "_user_owns_container", staticmethod(fake_owns))
    monkeypatch.setattr(
        EditorConsumer, "_get_container_with_node", staticmethod(fake_get_container)
    )
    monkeypatch.setattr(EditorConsumer, "_service", fake_service)
    monkeypatch.setattr(EditorConsumer, "_first_start_of_container", noop_first_start)
    monkeypatch.setattr(EditorConsumer, "audit_ws", noop_audit)
    monkeypatch.setattr(EditorConsumer, "_get_rev", fake_get_rev)
    monkeypatch.setattr(EditorConsumer, "_bump_rev", fake_bump_rev)


# --------------------------------------------------------------------------- #
# connect rejection paths
# --------------------------------------------------------------------------- #
def test_editor_anonymous_denied():
    app = build_app(AnonymousUser())

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/1/fs/")
        connected, _ = await comm.connect()
        assert connected is False

    asyncio.run(_main())


def test_editor_unauthorized_closed(monkeypatch):
    user = create_user(username="ed_unauth")
    _patch_consumer(monkeypatch, owns=False)
    app = build_app(user)

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/42/fs/")
        connected, _ = await comm.connect()
        assert connected is False

    asyncio.run(_main())


def test_editor_db_error_closed(monkeypatch):
    user = create_user(username="ed_dberr")
    _patch_consumer(monkeypatch, owns_error=True)
    app = build_app(user)

    async def _main():
        comm = WebsocketCommunicator(app, "/ws/containers/42/fs/")
        connected, _ = await comm.connect()
        assert connected is False

    asyncio.run(_main())


def test_editor_missing_container_closed(monkeypatch):
    user = create_user(username="ed_missing")
    _patch_consumer(monkeypatch, vm_client=FakeVMClient(), container=None)
    app = build_app(user)

    async def _main():
        # pk that does not exist -> _get_container_with_node returns None
        comm = WebsocketCommunicator(app, "/ws/containers/9999999/fs/")
        connected, _ = await comm.connect()
        assert connected is True  # accept() happens before the lookup
        # the consumer then closes with 4404 (no "connected" event is sent)
        response = await comm.receive_output(timeout=1)
        assert response["type"] == "websocket.close"
        await comm.disconnect()

    asyncio.run(_main())


# --------------------------------------------------------------------------- #
# connected + handlers
# --------------------------------------------------------------------------- #
def _connect(monkeypatch, vm_client):
    user = create_user(username="ed_ok")
    _patch_consumer(monkeypatch, vm_client=vm_client)
    app = build_app(user)
    comm = WebsocketCommunicator(app, "/ws/containers/7/fs/")
    return comm


def test_editor_handlers_happy_path(monkeypatch):
    vm = FakeVMClient()
    comm = _connect(monkeypatch, vm)

    async def _main():
        connected, _ = await comm.connect()
        assert connected is True
        hello = await comm.receive_json_from()
        assert hello == {"event": "connected"}

        # list_dirs
        await comm.send_json_to({"action": "list_dirs", "req_id": 1, "path": "/app"})
        msg = await comm.receive_json_from()
        assert msg["event"] == "ok" and msg["data"]["entries"][0]["name"] == "a.py"

        # read_file (rev injected from stubbed _get_rev)
        await comm.send_json_to(
            {"action": "read_file", "req_id": 2, "path": "/app/a.py"}
        )
        msg = await comm.receive_json_from()
        assert msg["data"]["content"] == "print(1)" and msg["data"]["rev"] == 5

        # create_dir (broadcasts file_changed AND replies ok)
        await comm.send_json_to(
            {"action": "create_dir", "req_id": 3, "path": "/app/sub"}
        )
        replies = [await comm.receive_json_from(), await comm.receive_json_from()]
        events = {r["event"] for r in replies}
        assert {"file_changed", "ok"} <= events

        # write_file, no conflict (prev_rev=0 skips the check)
        await comm.send_json_to(
            {
                "action": "write_file",
                "req_id": 4,
                "path": "/app/a.py",
                "content": "x=2",
                "prev_rev": 0,
            }
        )
        replies = [await comm.receive_json_from(), await comm.receive_json_from()]
        assert any(r["event"] == "ok" and r.get("rev") == 6 for r in replies)

        # search
        await comm.send_json_to(
            {"action": "search", "req_id": 5, "root": "/app", "pattern": "print"}
        )
        msg = await comm.receive_json_from()
        assert msg["event"] == "ok" and msg["data"][0]["path"] == "/app/a.py"

        # move_path
        await comm.send_json_to(
            {"action": "move_path", "req_id": 6, "src": "/app/a.py", "dst": "/app/b.py"}
        )
        replies = [await comm.receive_json_from(), await comm.receive_json_from()]
        assert any(r["event"] == "path_moved" for r in replies)

        # delete_path
        await comm.send_json_to(
            {"action": "delete_path", "req_id": 7, "path": "/app/b.py"}
        )
        replies = [await comm.receive_json_from(), await comm.receive_json_from()]
        assert any(r["event"] == "path_deleted" for r in replies)

        await comm.disconnect()

    asyncio.run(_main())
    kinds = [c[0] for c in vm.calls]
    assert "list_dirs" in kinds and "read_file" in kinds and "execute_sh" in kinds


def test_editor_write_conflict(monkeypatch):
    comm = _connect(monkeypatch, FakeVMClient())

    async def _main():
        await comm.connect()
        await comm.receive_json_from()  # connected
        # current rev is stubbed to 5; prev_rev=3 mismatches -> conflict
        await comm.send_json_to(
            {
                "action": "write_file",
                "req_id": 1,
                "path": "/app/a.py",
                "content": "x",
                "prev_rev": 3,
            }
        )
        msg = await comm.receive_json_from()
        assert (
            msg["event"] == "error" and msg["error"] == "conflict" and msg["rev"] == 5
        )
        await comm.disconnect()

    asyncio.run(_main())


def test_editor_unknown_action_and_bad_path(monkeypatch):
    comm = _connect(monkeypatch, FakeVMClient())

    async def _main():
        await comm.connect()
        await comm.receive_json_from()  # connected

        await comm.send_json_to({"action": "nope", "req_id": 1})
        msg = await comm.receive_json_from()
        assert msg["event"] == "error" and "unknown action" in msg["error"]

        # path outside /app raises ValueError -> surfaced as error
        await comm.send_json_to(
            {"action": "read_file", "req_id": 2, "path": "/etc/passwd"}
        )
        msg = await comm.receive_json_from()
        assert msg["event"] == "error" and "under /app" in msg["error"]

        await comm.disconnect()

    asyncio.run(_main())
