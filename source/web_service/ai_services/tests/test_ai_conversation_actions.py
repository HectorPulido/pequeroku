"""Conversation management actions on the consumer (list / new / switch / delete).

Drives ``AIConsumer._handle_action`` directly with an in-memory conversation
store (``convo`` monkeypatched), capturing the WS events it emits. No VM, no DB.
"""
from __future__ import annotations

import types

import pytest

import ai_services.ai_consumers as ai_consumers
from ai_services.ai_consumers import AIConsumer


def _make(monkeypatch, convs=None, current=1):
    convs = {1: []} if convs is None else dict(convs)
    state = {"current": current}

    monkeypatch.setattr(ai_consumers.convo, "list_conversation_ids", lambda c: sorted(convs.keys()))
    monkeypatch.setattr(ai_consumers.convo, "read_conversation", lambda c, cid: list(convs.get(cid, [])))

    def _write(c, cid, msgs):
        convs[cid] = list(msgs)

    monkeypatch.setattr(ai_consumers.convo, "write_conversation", _write)

    def _set_current(u, c, cid):
        state["current"] = cid

    monkeypatch.setattr(ai_consumers.convo, "set_current_id", _set_current)
    monkeypatch.setattr(
        ai_consumers.convo, "get_current_id", lambda u, c: state["current"]
    )

    def _delete(c, cid):
        convs.pop(cid, None)

    monkeypatch.setattr(ai_consumers.convo, "delete_conversation", _delete)

    consumer = AIConsumer()
    consumer.container_obj = types.SimpleNamespace(container_id="vm-1", node=object())
    consumer.user = object()
    consumer.conversation_id = current
    sent: list[dict] = []

    async def fake_send_json(data, **kwargs):
        sent.append(data)

    consumer.send_json = fake_send_json  # type: ignore[assignment]
    return consumer, sent, convs, state


def _events(sent, event_type):
    return [m for m in sent if m.get("event") == event_type]


async def test_list_conversations_action(monkeypatch):
    consumer, sent, _convs, _state = _make(
        monkeypatch, convs={1: [], 2: []}, current=2
    )
    await consumer._handle_action("list_conversations", {})
    convo_events = _events(sent, "conversations")
    assert convo_events
    assert convo_events[-1]["conversations"] == [1, 2]
    assert convo_events[-1]["current"] == 2


async def test_new_conversation_action_allocates_next_id(monkeypatch):
    consumer, sent, convs, state = _make(monkeypatch, convs={1: [], 2: []}, current=1)
    await consumer._handle_action("new_conversation", {})
    assert consumer.conversation_id == 3
    assert 3 in convs  # an (empty) file was created so it lists
    assert state["current"] == 3
    assert _events(sent, "clear")
    assert _events(sent, "conversations")[-1]["current"] == 3


async def test_switch_conversation_action_replays_history(monkeypatch):
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi back"},
    ]
    consumer, sent, _convs, state = _make(
        monkeypatch, convs={1: [], 2: history}, current=1
    )
    await consumer._handle_action("switch_conversation", {"id": 2})
    assert consumer.conversation_id == 2
    assert state["current"] == 2
    assert consumer.messages == history
    # the switched conversation's text is replayed to the client
    texts = [m.get("content") for m in _events(sent, "text")]
    assert "hello" in texts and "hi back" in texts
    assert _events(sent, "clear")


async def test_switch_conversation_ignores_bad_id(monkeypatch):
    consumer, sent, _convs, _state = _make(monkeypatch, current=1)
    await consumer._handle_action("switch_conversation", {"id": "nope"})
    assert consumer.conversation_id == 1  # unchanged


async def test_delete_current_conversation_falls_back(monkeypatch):
    consumer, sent, convs, _state = _make(
        monkeypatch, convs={1: [], 2: []}, current=2
    )
    await consumer._handle_action("delete_conversation", {"id": 2})
    assert 2 not in convs
    assert consumer.conversation_id == 1  # fell back to the remaining one
    assert _events(sent, "conversations")[-1]["current"] == 1
