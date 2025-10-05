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


class FakeAgent:
    """
    Minimal fake Agent that the AIConsumer expects:
    - has attribute `model`
    - async run_tool_loop(self, messages, summary_tools, on_tool_call, container=...)
      returns (messages, token_usage)
    - async get_response_no_tools(self, messages, response_while_thinking, on_chunk, on_finish)
      streams chunks via on_chunk, then on_finish, and returns (messages_with_assistant, token_usage)
    """

    def __init__(
        self, chunks=None, final_text="Hi there!", usage_tools=None, usage_resp=None
    ):
        self.model = "gpt-mocked"
        self._chunks = chunks or ["Hi", " there"]
        self._final_text = final_text
        # usage dicts: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        self._usage_tools = usage_tools or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._usage_resp = usage_resp or {
            "prompt_tokens": 0,
            "completion_tokens": len(self._chunks),
            "total_tokens": len(self._chunks),
        }

    async def run_tool_loop(self, messages, summary_tools, on_tool_call=None, **kwargs):
        # No tool calls; return unchanged messages and usage
        return messages, self._usage_tools

    async def get_response_no_tools(
        self,
        messages,
        response_while_thinking,
        on_chunk=None,
        on_finish=None,
    ):
        # Stream chunks
        for ch in self._chunks:
            if on_chunk is not None:
                await on_chunk(ch)

        # Append final assistant message
        new_messages = list(messages)
        new_messages.append({"role": "assistant", "content": self._final_text})

        # Notify finish
        if on_finish is not None:
            await on_finish(self._final_text)

        return new_messages, self._usage_resp


def build_auth_app(user, route):
    # Minimal auth middleware to inject the test user into scope
    class FakeAuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["user"] = user
            return await self.app(scope, receive, send)

    return FakeAuthMiddleware(URLRouter(route))


async def drain_until(comm: WebsocketCommunicator, predicate, timeout=2.0):
    """
    Drain incoming events until predicate(event_dict) returns True
    or timeout expires. Returns the matched event or last received.
    """
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


def test_ai_consumer_with_mocked_agent_streams_and_updates_quota(monkeypatch):
    # Arrange DB objects outside the event loop to avoid sync ORM from async context
    user = create_user(username="mocked_agent_user", password="secret")
    create_quota(user=user, ai_use_per_day=3)
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-mocked-1")

    # Patch the consumer module and inject our FakeAgent instance
    import ai_services.ai_consumers as ai_consumers
    import ai_services.ai_engineer as ai_engineer

    fake_agent = FakeAgent(chunks=["Hola", " mundo", "!"], final_text="Hola mundo!")
    # Patch both consumer-level and ai_engineer agent to avoid real API calls
    monkeypatch.setattr(ai_consumers, "agent", fake_agent)
    monkeypatch.setattr(ai_engineer, "agent", fake_agent)

    # Fake run_pipeline to simulate streaming and avoid network usage
    async def fake_run_pipeline(
        query,
        messages,
        container_obj,
        on_chunk,
        on_tool_call,
        on_start_chunking,
        on_finish_chunking,
    ):
        new_messages = list(messages)
        new_messages.append({"role": "user", "content": query})
        # start stream event
        await on_start_chunking()
        # stream chunks and finish
        streamed_messages, _ = await fake_agent.get_response_no_tools(
            new_messages, False, on_chunk=on_chunk, on_finish=on_finish_chunking
        )
        # return messages and a dummy token usage
        return streamed_messages, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    monkeypatch.setattr(ai_consumers, "run_pipeline", fake_run_pipeline, raising=True)

    # Patch static DB helpers to avoid cross-thread issues and to simulate quota decrease
    calls = {"uses": 3, "memory": []}

    async def fake_get_quota(user_id):
        return object(), calls["uses"]

    async def fake_set_quota(user, query, response, container, token_usage):
        # decrement uses once per full exchange
        calls["uses"] = max(calls["uses"] - 1, 0)

    async def fake_set_memory(user, container, memory_data):
        calls["memory"] = memory_data

    async def fake_get_memory(user, container):
        # start with empty memory
        return []

    async def fake_get_container_simple(pk):
        return container

    async def fake_user_owns_container(pk, user_pk):
        return True

    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_quota", staticmethod(fake_get_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_set_quota", staticmethod(fake_set_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_set_memory", staticmethod(fake_set_memory)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_memory", staticmethod(fake_get_memory)
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

    # Build ASGI app
    route = [re_path(r"^ws/ai/(?P<pk>\d+)/$", ai_consumers.AIConsumer.as_asgi())]
    app = build_auth_app(user, route)

    async def _main():
        # Connect
        communicator = WebsocketCommunicator(app, f"/ws/ai/{container.pk}/")
        connected, _ = await communicator.connect()
        assert connected is True

        evt = await drain_until(communicator, lambda e: e.get("event") == "connected")
        assert evt and evt.get("event") == "connected"
        assert isinstance(evt.get("ai_uses_left_today"), int)
        uses_initial = evt["ai_uses_left_today"]

        # Send a message to trigger the flow
        await communicator.send_json_to({"text": "hola"})

        # Expect placeholder
        start_evt = await drain_until(
            communicator, lambda e: e.get("event") == "start_text"
        )
        assert start_evt and start_evt.get("event") == "start_text"

        placeholder = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and e.get("content") == "...",
        )
        assert placeholder and placeholder.get("content") == "..."

        # Then a new start_text for streaming
        start_stream = await drain_until(
            communicator, lambda e: e.get("event") == "start_text"
        )
        assert start_stream and start_stream.get("event") == "start_text"

        # Streamed chunks from FakeAgent via on_chunk
        ch1 = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and "Hola" in e.get("content", ""),
        )
        assert ch1 and "Hola" in ch1.get("content", "")

        ch2 = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and "mundo" in e.get("content", ""),
        )
        assert ch2 and "mundo" in ch2.get("content", "")

        ch3 = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and "!" in e.get("content", ""),
        )
        assert ch3 and "!" in ch3.get("content", "")

        # Finish event from on_finish
        finish_evt = await drain_until(
            communicator, lambda e: e.get("event") == "finish_text"
        )
        assert finish_evt and finish_evt.get("event") == "finish_text"

        # Memory should be sent and include the assistant message
        memory_evt = await drain_until(
            communicator, lambda e: e.get("event") == "memory_data"
        )
        assert memory_evt and isinstance(memory_evt.get("memory"), list)
        # Last message should be our assistant text
        assert memory_evt["memory"][-1]["role"] == "assistant"
        assert memory_evt["memory"][-1]["content"] == "Hola mundo!"

        # Quota updated event
        evt2 = await drain_until(communicator, lambda e: e.get("event") == "connected")
        assert evt2 and evt2.get("event") == "connected"
        assert evt2["ai_uses_left_today"] <= uses_initial

        await communicator.disconnect()

    asyncio.run(_main())
