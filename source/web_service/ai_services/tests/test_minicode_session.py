"""Persistence-resilience tests for minicode/session.py.

save()/load() are best-effort: a bad path or corrupt file must never raise — the
agent keeps running with whatever (possibly empty) history it has.
"""

from __future__ import annotations

from ai_services.minicode.session import Session


def test_save_noop_without_memory_path(tmp_path):
    s = Session()  # no memory_path
    s.add_user("hi")
    s.save()  # must be a no-op and not raise


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "mem.json")
    s = Session(memory_path=path)
    s.add_user("hello")
    s.add_assistant("hi there", [])
    s.todos = [{"content": "do x", "status": "pending"}]
    s.save()

    restored = Session.load(path)
    assert restored.last_assistant_text() == "hi there"
    assert restored.todos == [{"content": "do x", "status": "pending"}]
    assert any(
        m["role"] == "user" and m["content"] == "hello" for m in restored.messages
    )


def test_save_swallows_unwritable_path(tmp_path):
    # A path whose parent directory does not exist -> write raises -> swallowed.
    bad = str(tmp_path / "missing_dir" / "mem.json")
    s = Session(memory_path=bad)
    s.add_user("hi")
    s.save()  # must not raise


def test_load_missing_file_returns_empty_session(tmp_path):
    s = Session.load(str(tmp_path / "does-not-exist.json"))
    assert s.messages == [] and s.todos == []


def test_load_corrupt_json_returns_empty_session(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json", encoding="utf-8")
    s = Session.load(str(path))
    assert s.messages == [] and s.todos == []


def test_load_sanitizes_dangling_tool_calls(tmp_path):
    # A persisted history with an assistant.tool_calls but no answering tool must be
    # repaired on load (otherwise the API rejects the next call).
    import json

    path = tmp_path / "mem.json"
    path.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "q"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "read", "arguments": "{}"},
                            }
                        ],
                    },
                ],
                "todos": [],
            }
        ),
        encoding="utf-8",
    )
    s = Session.load(str(path))
    tool_msgs = [m for m in s.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["tool_call_id"] == "c1"
