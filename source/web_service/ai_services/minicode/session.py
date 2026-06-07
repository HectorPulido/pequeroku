"""Conversation state + persistent memory + self-repair.

Stores the messages in the exact format the OpenAI-style API understands
(``role``/``content``/``tool_calls``/``tool``), which is what gets sent back to the
model on each turn of the loop. Persisting and re-reading this history is precisely
what lets the model "see" the results of its tools on the next step.

Memory: if ``memory_path`` is set, ``save()`` dumps the conversation to a JSON
file. When starting in the same workdir, ``load()`` restores it.

Resilience: ``sanitize()`` repairs broken histories (an assistant with
``tool_calls`` lacking its answering ``tool``), which would otherwise make the API
return 400 on EVERY subsequent call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_ABORTED = "Tool execution was interrupted; no result was produced."


class Session:
    def __init__(self, memory_path: Optional[str] = None) -> None:
        # Messages in OpenAI format (excluding the system, which is prepended each turn).
        self.messages: list[dict] = []
        # Task list managed by the todowrite tool.
        self.todos: list[dict] = []
        self.memory_path = memory_path

    # -- mutations -------------------------------------------------------
    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: str, tool_calls: list[dict]) -> None:
        msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def last_assistant_text(self) -> str:
        for m in reversed(self.messages):
            if m["role"] == "assistant" and m.get("content"):
                return m["content"]
        return ""

    # -- resilience ------------------------------------------------------
    def sanitize(self) -> None:
        """Ensure each ``assistant`` with ``tool_calls`` is followed by one ``tool``
        per id, and drop orphan ``tool`` messages. Idempotent.
        """
        repaired: list[dict] = []
        msgs = self.messages
        n = len(msgs)
        i = 0
        while i < n:
            m = msgs[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                repaired.append(m)
                needed = [tc["id"] for tc in m["tool_calls"]]
                j = i + 1
                provided: dict = {}
                while j < n and msgs[j].get("role") == "tool":
                    provided[msgs[j].get("tool_call_id")] = msgs[j]
                    j += 1
                for tid in needed:
                    repaired.append(
                        provided.get(
                            tid,
                            {"role": "tool", "tool_call_id": tid, "content": _ABORTED},
                        )
                    )
                i = j
            elif m.get("role") == "tool":
                i += 1  # orphan (no preceding assistant.tool_calls): discard it
            else:
                repaired.append(m)
                i += 1
        self.messages = repaired

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        if not self.memory_path:
            return
        self.sanitize()
        try:
            Path(self.memory_path).write_text(
                json.dumps(
                    {"messages": self.messages, "todos": self.todos}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
        except Exception:
            pass  # memory is best-effort; it must never bring the agent down

    @classmethod
    def load(cls, memory_path: str) -> "Session":
        s = cls(memory_path=memory_path)
        try:
            data = json.loads(Path(memory_path).read_text(encoding="utf-8"))
            s.messages = data.get("messages", []) or []
            s.todos = data.get("todos", []) or []
            s.sanitize()
        except Exception:
            pass
        return s
