"""Tests for the memory tools (ai_services/minicode/tools/memory.py):
full CRUD with upsert-by-id on save and edit, and exact-id delete.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ai_services.minicode.config import Config
from ai_services.minicode.session import Session
from ai_services.minicode.tools import tools_for
from ai_services.minicode.tools.base import ToolContext
from ai_services.minicode.tools import memory as m


class FakeVMClient:
    """Minimal VM client: a path -> text dict, like the file-tool tests use."""

    def __init__(self):
        self.fs: dict[str, str] = {}

    def read_file(self, cid, path):
        return {
            "name": path.rsplit("/", 1)[-1],
            "content": self.fs.get(path, ""),
            "length": len(self.fs.get(path, "")),
            "found": path in self.fs,
        }

    def upload_files(self, cid, payload):
        for vf in payload.files:
            self.fs[vf.path] = vf.text or ""
        return {"ok": True}


_MEMORY_PATH = "/app/.pequenin/memory.json"


def make_ctx(client):
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = client
    return ToolContext(
        config=config, session=Session(), spawn_subagent=lambda *a: iter(())
    )


def _stored(client) -> dict:
    return json.loads(client.fs[_MEMORY_PATH])


# --------------------------------------------------------------------------- #
# save_memory (create)
# --------------------------------------------------------------------------- #
def test_save_creates_file_and_slug_id_from_content():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = m.SaveMemoryTool().execute({"content": "Auth uses JWT in cookies"}, ctx)
    assert "Saved memory 'auth-uses-jwt-in-cookies'" in out
    data = _stored(client)
    assert data["auth-uses-jwt-in-cookies"]["content"] == "Auth uses JWT in cookies"
    assert "created_at" in data["auth-uses-jwt-in-cookies"]


def test_save_requires_content():
    ctx = make_ctx(FakeVMClient())
    out = m.SaveMemoryTool().execute({"content": "   "}, ctx)
    assert out.startswith("Error:")


def test_save_explicit_id_is_slugified():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = m.SaveMemoryTool().execute({"id": "DB Engine", "content": "Postgres 16"}, ctx)
    assert "Saved memory 'db-engine'" in out
    assert list(_stored(client)) == ["db-engine"]


def test_save_same_content_no_id_is_deduped():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"content": "Same fact"}, ctx)
    out = m.SaveMemoryTool().execute({"content": "Same fact"}, ctx)
    assert "already saved" in out
    assert list(_stored(client)) == ["same-fact"]


def test_save_colliding_slug_different_content_suffixes():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"content": "same!!!"}, ctx)
    m.SaveMemoryTool().execute({"content": "same???"}, ctx)
    assert set(_stored(client)) == {"same", "same-2"}


def test_save_distinct_ids_accumulate():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "a", "content": "first"}, ctx)
    m.SaveMemoryTool().execute({"id": "b", "content": "second"}, ctx)
    assert set(_stored(client)) == {"a", "b"}


# --------------------------------------------------------------------------- #
# save_memory (upsert by exact id)
# --------------------------------------------------------------------------- #
def test_save_existing_id_updates_in_place():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "db", "content": "Postgres 16"}, ctx)
    created = _stored(client)["db"]["created_at"]
    out = m.SaveMemoryTool().execute({"id": "db", "content": "Postgres 17"}, ctx)
    assert "Updated memory 'db'" in out
    entry = _stored(client)["db"]
    assert entry["content"] == "Postgres 17"
    assert entry["created_at"] == created  # preserved
    assert "updated_at" in entry
    assert list(_stored(client)) == ["db"]  # not duplicated


# --------------------------------------------------------------------------- #
# read_memories
# --------------------------------------------------------------------------- #
def test_read_empty_when_no_file():
    ctx = make_ctx(FakeVMClient())
    assert m.ReadMemoryTool().execute({}, ctx) == "(no memories saved yet)"


def test_read_lists_saved_memories():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "auth", "content": "JWT in cookies"}, ctx)
    m.SaveMemoryTool().execute({"id": "db", "content": "Postgres 16"}, ctx)
    out = m.ReadMemoryTool().execute({}, ctx)
    assert "Saved memories (2):" in out
    assert "- [auth]" in out and "JWT in cookies" in out
    assert "- [db]" in out and "Postgres 16" in out


def test_read_tolerates_corrupt_json():
    client = FakeVMClient()
    client.fs[_MEMORY_PATH] = "{ not valid json"
    ctx = make_ctx(client)
    assert m.ReadMemoryTool().execute({}, ctx) == "(no memories saved yet)"


# --------------------------------------------------------------------------- #
# edit_memory (upsert)
# --------------------------------------------------------------------------- #
def test_edit_updates_content_and_preserves_created_at():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "db", "content": "Postgres 16"}, ctx)
    created = _stored(client)["db"]["created_at"]
    out = m.EditMemoryTool().execute({"id": "db", "content": "Postgres 17"}, ctx)
    assert "Updated memory 'db'" in out
    entry = _stored(client)["db"]
    assert entry["content"] == "Postgres 17"
    assert entry["created_at"] == created
    assert "updated_at" in entry
    assert list(_stored(client)) == ["db"]


def test_edit_creates_when_id_missing():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = m.EditMemoryTool().execute({"id": "New Thing", "content": "value"}, ctx)
    assert "Created memory 'new-thing'" in out
    entry = _stored(client)["new-thing"]
    assert entry["content"] == "value"
    assert "created_at" in entry and "updated_at" not in entry


def test_edit_requires_content():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "db", "content": "Postgres"}, ctx)
    out = m.EditMemoryTool().execute({"id": "db", "content": ""}, ctx)
    assert out.startswith("Error:")


# --------------------------------------------------------------------------- #
# delete_memory (exact id)
# --------------------------------------------------------------------------- #
def test_delete_removes_memory():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "a", "content": "one"}, ctx)
    m.SaveMemoryTool().execute({"id": "b", "content": "two"}, ctx)
    out = m.DeleteMemoryTool().execute({"id": "a"}, ctx)
    assert "Deleted memory 'a'" in out
    assert list(_stored(client)) == ["b"]


def test_delete_missing_id_errors_and_lists_saved():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"id": "database", "content": "pg"}, ctx)
    out = m.DeleteMemoryTool().execute({"id": "ghost"}, ctx)
    assert "no memory with id 'ghost'" in out and "database" in out
    assert list(_stored(client)) == ["database"]  # nothing deleted


def test_delete_on_empty_store_reports_none_saved():
    ctx = make_ctx(FakeVMClient())
    out = m.DeleteMemoryTool().execute({"id": "x"}, ctx)
    assert "no memories saved yet" in out


# --------------------------------------------------------------------------- #
# flags + registration per agent type
# --------------------------------------------------------------------------- #
def test_read_only_flags():
    assert m.ReadMemoryTool.read_only is True
    assert m.SaveMemoryTool.read_only is False
    assert m.EditMemoryTool.read_only is False
    assert m.DeleteMemoryTool.read_only is False


def test_registration_per_agent_type():
    build = {t.name for t in tools_for("build")}
    general = {t.name for t in tools_for("general")}
    explore = {t.name for t in tools_for("explore")}
    crud = {"save_memory", "read_memories", "edit_memory", "delete_memory"}
    assert crud <= build  # main agent: full CRUD
    assert crud <= general  # worker subagent: full CRUD
    # read-only subagent: recall only, no mutation
    assert "read_memories" in explore
    assert not (explore & (crud - {"read_memories"}))


def test_roundtrip_save_then_read():
    client = FakeVMClient()
    ctx = make_ctx(client)
    m.SaveMemoryTool().execute({"content": "User prefers pnpm over npm"}, ctx)
    out = m.ReadMemoryTool().execute({}, ctx)
    assert "User prefers pnpm over npm" in out
