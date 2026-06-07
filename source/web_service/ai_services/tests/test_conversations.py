"""Tests for ai_services.conversations.

Conversation CONTENT lives in the VM (tested with a fake VMServiceClient, no DB);
the active-conversation POINTER lives in the DB (tested with django_db).
"""

from __future__ import annotations

import json
import types

import pytest

import ai_services.conversations as convo
from vm_manager.test_utils import create_user, create_node, create_container


class FakeService:
    def __init__(self, files=None, dirs=None):
        self.files: dict[str, str] = dict(files or {})  # path -> content
        self.dir_entries: list[str] = list(dirs or [])  # names under MEMORY_DIR
        self.execced: list[str] = []

    def read_file(self, vm_id, path):
        if path in self.files:
            return {"found": True, "content": self.files[path]}
        return {"found": False, "content": ""}

    def upload_files(self, vm_id, payload):
        for f in payload.files:
            self.files[f.path] = f.text
        return {"ok": True}

    def list_dirs(self, vm_id, paths):
        return [
            {"path": f"{convo.MEMORY_DIR}/{n}", "name": n, "path_type": "file"}
            for n in self.dir_entries
        ]

    def execute_sh(self, vm_id, command):
        self.execced.append(command)
        return {"ok": True, "stdout": "", "stderr": ""}


class RaisingService:
    """Every VM call blows up — simulates an unreachable / not-ready VM."""

    def read_file(self, vm_id, path):
        raise RuntimeError("vm unreachable")

    def upload_files(self, vm_id, payload):
        raise RuntimeError("vm unreachable")

    def list_dirs(self, vm_id, paths):
        raise RuntimeError("vm unreachable")

    def execute_sh(self, vm_id, command):
        raise RuntimeError("vm unreachable")


@pytest.fixture
def container():
    return types.SimpleNamespace(container_id="vm-1", node=object())


def _patch(monkeypatch, service):
    monkeypatch.setattr(convo, "VMServiceClient", lambda node: service)


# --------------------------------------------------------------------------- #
# VM-backed conversation content (no DB)
# --------------------------------------------------------------------------- #
def test_paths():
    assert convo.memory_path(3) == "/app/.pequenin/ai_memory_3.json"


def test_write_then_read_conversation(monkeypatch, container):
    svc = FakeService()
    _patch(monkeypatch, svc)
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]

    convo.write_conversation(container, 2, msgs)
    assert convo.memory_path(2) in svc.files
    assert json.loads(svc.files[convo.memory_path(2)])["messages"] == msgs
    assert convo.read_conversation(container, 2) == msgs


def test_read_missing_conversation_is_empty(monkeypatch, container):
    _patch(monkeypatch, FakeService())
    assert convo.read_conversation(container, 9) == []


def test_list_conversation_ids_parses_filters_and_sorts(monkeypatch, container):
    svc = FakeService(
        dirs=[
            "ai_memory_2.json",
            "ai_memory_1.json",
            "notes.txt",
            "ai_memory_x.json",
        ]
    )
    _patch(monkeypatch, svc)
    assert convo.list_conversation_ids(container) == [1, 2]


def test_next_conversation_id(monkeypatch, container):
    _patch(monkeypatch, FakeService(dirs=["ai_memory_1.json", "ai_memory_4.json"]))
    assert convo.next_conversation_id(container) == 5
    _patch(monkeypatch, FakeService())
    assert convo.next_conversation_id(container) == 1


def test_delete_conversation_runs_rm(monkeypatch, container):
    svc = FakeService()
    _patch(monkeypatch, svc)
    convo.delete_conversation(container, 3)
    assert any("rm -f" in c and "ai_memory_3.json" in c for c in svc.execced)


# --------------------------------------------------------------------------- #
# error handling: a failing VM never propagates (best-effort, degrade quietly)
# --------------------------------------------------------------------------- #
def test_read_json_swallows_vm_error(monkeypatch, container):
    _patch(monkeypatch, RaisingService())
    assert convo.read_json(container, "/app/.pequenin/x.json") is None
    assert convo.read_conversation(container, 1) == []


def test_read_json_swallows_bad_json(monkeypatch, container):
    _patch(monkeypatch, FakeService(files={"/app/.pequenin/x.json": "{not json"}))
    assert convo.read_json(container, "/app/.pequenin/x.json") is None


def test_write_json_swallows_vm_error(monkeypatch, container):
    _patch(monkeypatch, RaisingService())
    # must not raise even though upload blows up
    convo.write_conversation(container, 1, [{"role": "user", "content": "hi"}])


def test_list_conversation_ids_swallows_vm_error(monkeypatch, container):
    _patch(monkeypatch, RaisingService())
    assert convo.list_conversation_ids(container) == []
    assert convo.next_conversation_id(container) == 1  # falls back to 1


def test_delete_conversation_swallows_vm_error(monkeypatch, container):
    _patch(monkeypatch, RaisingService())
    convo.delete_conversation(container, 3)  # must not raise


@pytest.mark.django_db
def test_get_current_id_swallows_db_error(monkeypatch):
    # Force the ORM query to raise -> get_current_id returns None, not a crash.
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(convo.AIMemory.objects, "filter", boom)
    container = types.SimpleNamespace(container_id="vm-1", node=object())
    assert convo.get_current_id(object(), container) is None


# --------------------------------------------------------------------------- #
# DB-backed active-conversation pointer (durable)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_current_id_pointer_roundtrip_and_default():
    user = create_user("convo-ptr")
    container = create_container(
        user=user, node=create_node(name="np"), container_id="vm-ptr"
    )
    assert convo.get_current_id(user, container) is None  # no row yet
    convo.set_current_id(user, container, 5)
    assert convo.get_current_id(user, container) == 5
    convo.set_current_id(user, container, 7)  # update, not duplicate
    assert convo.get_current_id(user, container) == 7


@pytest.mark.django_db
def test_list_with_current_uses_db_pointer(monkeypatch):
    user = create_user("convo-lwc")
    container = create_container(
        user=user, node=create_node(name="nl"), container_id="vm-lwc"
    )
    _patch(monkeypatch, FakeService(dirs=["ai_memory_1.json", "ai_memory_2.json"]))
    convo.set_current_id(user, container, 2)
    assert convo.list_with_current(user, container) == {
        "conversations": [1, 2],
        "current": 2,
    }


@pytest.mark.django_db
def test_list_with_current_defaults_when_empty(monkeypatch):
    user = create_user("convo-empty")
    container = create_container(
        user=user, node=create_node(name="ne"), container_id="vm-empty"
    )
    _patch(monkeypatch, FakeService())
    assert convo.list_with_current(user, container) == {
        "conversations": [1],
        "current": 1,
    }


@pytest.mark.django_db
def test_list_with_current_dangling_pointer_falls_back(monkeypatch):
    user = create_user("convo-dang")
    container = create_container(
        user=user, node=create_node(name="nd"), container_id="vm-dang"
    )
    _patch(monkeypatch, FakeService(dirs=["ai_memory_1.json"]))
    convo.set_current_id(user, container, 7)  # points to a file that doesn't exist
    assert convo.list_with_current(user, container) == {
        "conversations": [1],
        "current": 1,
    }
