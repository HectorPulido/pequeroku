"""History replay must re-emit the tool timeline, not just text turns.

Regression test for the bug where tool steps (tool_call/tool_result/todos) showed
live but vanished after a reload, because ``send_history`` surfaced only text turns
and dropped every message carrying tool data. ``_history_events`` rebuilds the SAME
events the live pipeline emits from the persisted OpenAI memory.
"""

from ai_services.ai_consumers import _history_events


def _events_of(memory, name):
    return [e for e in _history_events(memory) if e.get("event") == name]


def test_tool_call_and_result_are_replayed():
    memory = [
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": '{"command": "ls -la"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "total 0"},
        {"role": "assistant", "content": "Here are your files."},
    ]

    events = _history_events(memory)
    kinds = [e["event"] for e in events]

    # The user turn keeps its memory index (for forking) and the assistant's
    # intermediate prose, the tool call and its paired result all survive replay.
    assert kinds == [
        "start_text",
        "text",
        "finish_text",
        "start_text",
        "text",
        "finish_text",
        "tool_call",
        "tool_result",
        "start_text",
        "text",
        "finish_text",
    ]

    (user_start,) = [e for e in events if e.get("role") == "user"]
    assert user_start["index"] == 0

    (call,) = _events_of(memory, "tool_call")
    assert call["name"] == "bash"
    assert call["args"] == {"command": "ls -la"}
    assert call["command"] == "ls -la"  # synthesized exactly like the live path

    (result,) = _events_of(memory, "tool_result")
    assert result["name"] == "bash"
    assert result["output"] == "total 0"


def test_call_is_immediately_followed_by_its_result():
    """Pairing must be unambiguous even when a turn repeats a tool name."""
    memory = [
        {"role": "user", "content": "read both"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "a",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"filePath": "x"}'},
                },
                {
                    "id": "b",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"filePath": "y"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "X-CONTENT"},
        {"role": "tool", "tool_call_id": "b", "content": "Y-CONTENT"},
        {"role": "assistant", "content": "done"},
    ]

    tool_events = [
        e for e in _history_events(memory) if e["event"] in ("tool_call", "tool_result")
    ]

    # call(x) -> result(X) -> call(y) -> result(Y): each result sits right after its
    # own call, so the frontend's match-by-name never mispairs the two `read`s.
    assert [e["event"] for e in tool_events] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]
    assert tool_events[0]["command"] == "read x"
    assert tool_events[1]["output"] == "X-CONTENT"
    assert tool_events[2]["command"] == "read y"
    assert tool_events[3]["output"] == "Y-CONTENT"


def test_todowrite_also_emits_a_todos_event():
    todos = [{"content": "ship it", "status": "in_progress"}]
    memory = [
        {"role": "user", "content": "plan"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "t",
                    "type": "function",
                    "function": {
                        "name": "todowrite",
                        "arguments": '{"todos": [{"content": "ship it", "status": "in_progress"}]}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "t", "content": "ok"},
    ]

    (todos_evt,) = _events_of(memory, "todos")
    assert todos_evt["todos"] == todos


def test_text_only_history_is_unchanged():
    """Conversations without tools replay exactly as before (back-compat)."""
    memory = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "B"},
    ]

    events = _history_events(memory)
    assert [(e["event"], e.get("content")) for e in events] == [
        ("start_text", None),
        ("text", "a"),
        ("finish_text", None),
        ("start_text", None),
        ("text", "A"),
        ("finish_text", None),
        ("start_text", None),
        ("text", "b"),
        ("finish_text", None),
        ("start_text", None),
        ("text", "B"),
        ("finish_text", None),
    ]
    # User-turn indices still map to their stored-memory position (fork relies on it).
    user_indices = [e["index"] for e in events if e.get("role") == "user"]
    assert user_indices == [0, 2]


def test_orphan_tool_call_without_result_still_renders_the_call():
    """A persisted call whose result is missing must not drop the whole step."""
    memory = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "missing",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "true"}'},
                }
            ],
        },
    ]

    assert len(_events_of(memory, "tool_call")) == 1
    assert _events_of(memory, "tool_result") == []
