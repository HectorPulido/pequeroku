import asyncio
import pytest
from django.urls import re_path
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter

from vm_manager.test_utils import (
    create_user,
    create_quota,
    create_node,
    create_container,
)

pytestmark = pytest.mark.django_db


def build_auth_app(user, route):
    class FakeAuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["user"] = user
            return await self.app(scope, receive, send)

    return FakeAuthMiddleware(URLRouter(route))


async def drain_until(comm: WebsocketCommunicator, predicate, timeout=2.0):
    end = asyncio.get_event_loop().time() + timeout
    last = None
    while asyncio.get_event_loop().time() < end:
        try:
            data = await asyncio.wait_for(comm.receive_json_from(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        last = data
        if predicate(data):
            return data
    return last


def test_fork_conversation_branches_before_edited_message(monkeypatch):
    """Editing a user message forks the conversation just before it.

    Source memory (conversation 1):
        [user "a", assistant "A", user "b", assistant "B"]
    Forking at index 2 (the "b" user turn) must create a NEW conversation holding
    only ``memory[:2]`` (= [user "a", assistant "A"]), switch to it, and leave the
    source untouched.
    """
    user = create_user(username="fork_user", password="secret")
    create_quota(user=user, ai_use_per_day=3)
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-fork-1")

    import ai_services.ai_consumers as ai_consumers

    source_memory = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "B"},
    ]

    writes: dict = {}

    async def fake_get_quota(user_id):
        return object(), 3

    async def fake_get_container_simple(pk):
        return container

    async def fake_user_owns_container(pk, user_pk):
        return True

    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_quota", staticmethod(fake_get_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_get_container_simple",
        staticmethod(fake_get_container_simple),
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_user_owns_container",
        staticmethod(fake_user_owns_container),
    )

    # Conversation storage is stubbed so the consumer stays hermetic (no VM I/O).
    monkeypatch.setattr(ai_consumers.convo, "list_conversation_ids", lambda c: [1])
    monkeypatch.setattr(ai_consumers.convo, "get_current_id", lambda u, c: 1)
    monkeypatch.setattr(
        ai_consumers.convo, "read_conversation", lambda c, cid: list(source_memory)
    )
    monkeypatch.setattr(ai_consumers.convo, "set_current_id", lambda u, c, cid: None)

    def _fake_write_conversation(c, cid, messages):
        writes[cid] = messages

    monkeypatch.setattr(
        ai_consumers.convo, "write_conversation", _fake_write_conversation
    )

    route = [re_path(r"^ws/ai/(?P<pk>\d+)/$", ai_consumers.AIConsumer.as_asgi())]
    app = build_auth_app(user, route)

    async def _main():
        communicator = WebsocketCommunicator(app, f"/ws/ai/{container.pk}/")
        connected, _ = await communicator.connect()
        assert connected is True

        # Wait for the initial history replay + connected handshake.
        await drain_until(communicator, lambda e: e.get("event") == "connected")

        # Fork at the second user turn ("b") which lives at memory index 2. Send
        # both the explicit index and the ordinal; the index path takes priority.
        await communicator.send_json_to(
            {"action": "fork_conversation", "index": 2, "user_ordinal": 1}
        )

        # The branch emits a `clear` first.
        clear_evt = await drain_until(communicator, lambda e: e.get("event") == "clear")
        assert clear_evt and clear_evt.get("event") == "clear"

        # Replayed history of the new conversation: the first user turn "a" with its
        # memory index, then the assistant turn "A". The edited "b"/"B" are gone.
        a_start = await drain_until(
            communicator,
            lambda e: e.get("event") == "start_text" and e.get("role") == "user",
        )
        assert a_start and a_start.get("index") == 0

        a_text = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and e.get("content") == "a",
        )
        assert a_text and a_text.get("content") == "a"

        # No "b" should ever be replayed in the new conversation.
        conversations_evt = await drain_until(
            communicator, lambda e: e.get("event") == "conversations"
        )
        assert conversations_evt
        assert conversations_evt.get("current") == 2
        assert 2 in conversations_evt.get("conversations", [])

        # The new conversation (id 2) was written with exactly memory[:2]; the
        # source conversation (id 1) was never rewritten.
        assert writes.get(2) == [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "A"},
        ]
        assert 1 not in writes

        await communicator.disconnect()

    asyncio.run(_main())


def test_fork_conversation_by_ordinal_fallback(monkeypatch):
    """When no explicit index is sent, the user-bubble ordinal resolves the cut.

    Source: [user "a", assistant "A", user "b", assistant "B"]. user_ordinal 1 is
    the second user bubble ("b") at memory index 2, so the new conversation holds
    memory[:2] = [user "a", assistant "A"].
    """
    user = create_user(username="fork_ord_user", password="secret")
    create_quota(user=user, ai_use_per_day=3)
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-fork-ord")

    import ai_services.ai_consumers as ai_consumers

    source_memory = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "B"},
    ]
    writes: dict = {}

    async def fake_get_quota(user_id):
        return object(), 3

    async def fake_get_container_simple(pk):
        return container

    async def fake_user_owns_container(pk, user_pk):
        return True

    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_quota", staticmethod(fake_get_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_get_container_simple",
        staticmethod(fake_get_container_simple),
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_user_owns_container",
        staticmethod(fake_user_owns_container),
    )
    monkeypatch.setattr(ai_consumers.convo, "list_conversation_ids", lambda c: [1])
    monkeypatch.setattr(ai_consumers.convo, "get_current_id", lambda u, c: 1)
    monkeypatch.setattr(
        ai_consumers.convo, "read_conversation", lambda c, cid: list(source_memory)
    )
    monkeypatch.setattr(ai_consumers.convo, "set_current_id", lambda u, c, cid: None)
    monkeypatch.setattr(
        ai_consumers.convo,
        "write_conversation",
        lambda c, cid, messages: writes.__setitem__(cid, messages),
    )

    route = [re_path(r"^ws/ai/(?P<pk>\d+)/$", ai_consumers.AIConsumer.as_asgi())]
    app = build_auth_app(user, route)

    async def _main():
        communicator = WebsocketCommunicator(app, f"/ws/ai/{container.pk}/")
        connected, _ = await communicator.connect()
        assert connected is True
        await drain_until(communicator, lambda e: e.get("event") == "connected")

        # No explicit index — only the ordinal of the second user bubble.
        await communicator.send_json_to(
            {"action": "fork_conversation", "user_ordinal": 1}
        )

        conversations_evt = await drain_until(
            communicator, lambda e: e.get("event") == "conversations"
        )
        assert conversations_evt and conversations_evt.get("current") == 2
        assert writes.get(2) == [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "A"},
        ]
        assert 1 not in writes

        await communicator.disconnect()

    asyncio.run(_main())


def test_fork_conversation_rejects_non_user_index(monkeypatch):
    """Forking at a non-user message (or out-of-range index) is a no-op."""
    user = create_user(username="fork_user2", password="secret")
    create_quota(user=user, ai_use_per_day=3)
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-fork-2")

    import ai_services.ai_consumers as ai_consumers

    source_memory = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "A"},
    ]
    writes: dict = {}

    async def fake_get_quota(user_id):
        return object(), 3

    async def fake_get_container_simple(pk):
        return container

    async def fake_user_owns_container(pk, user_pk):
        return True

    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_quota", staticmethod(fake_get_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_get_container_simple",
        staticmethod(fake_get_container_simple),
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_user_owns_container",
        staticmethod(fake_user_owns_container),
    )
    monkeypatch.setattr(ai_consumers.convo, "list_conversation_ids", lambda c: [1])
    monkeypatch.setattr(ai_consumers.convo, "get_current_id", lambda u, c: 1)
    monkeypatch.setattr(
        ai_consumers.convo, "read_conversation", lambda c, cid: list(source_memory)
    )
    monkeypatch.setattr(ai_consumers.convo, "set_current_id", lambda u, c, cid: None)
    monkeypatch.setattr(
        ai_consumers.convo,
        "write_conversation",
        lambda c, cid, messages: writes.__setitem__(cid, messages),
    )

    route = [re_path(r"^ws/ai/(?P<pk>\d+)/$", ai_consumers.AIConsumer.as_asgi())]
    app = build_auth_app(user, route)

    async def _main():
        communicator = WebsocketCommunicator(app, f"/ws/ai/{container.pk}/")
        connected, _ = await communicator.connect()
        assert connected is True
        await drain_until(communicator, lambda e: e.get("event") == "connected")

        # Index 1 is the assistant turn → must be rejected (no new conversation).
        await communicator.send_json_to({"action": "fork_conversation", "index": 1})
        # Out-of-range index → also rejected.
        await communicator.send_json_to({"action": "fork_conversation", "index": 99})

        # Give the consumer a moment; no `clear`/write should result.
        clear_evt = await drain_until(
            communicator, lambda e: e.get("event") == "clear", timeout=1.0
        )
        assert clear_evt is None or clear_evt.get("event") != "clear"
        assert writes == {}

        await communicator.disconnect()

    asyncio.run(_main())
