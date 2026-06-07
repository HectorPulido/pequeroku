"""Common model of a tool + output truncation.

Equivalent to opencode's ``tool/tool.ts`` and ``tool/truncate.ts``: a uniform
interface (``Tool``), the ``ToolContext`` that ``execute`` receives, and automatic
truncation so a huge output doesn't blow up the context window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

MAX_OUTPUT_LINES = 2000
MAX_OUTPUT_BYTES = 50_000


def truncate(
    text: str,
    max_lines: int = MAX_OUTPUT_LINES,
    max_bytes: int = MAX_OUTPUT_BYTES,
    from_tail: bool = False,
) -> str:
    """Trim from the head (default) or the tail (``from_tail``, e.g. shell)."""
    truncated = False
    lines = text.split("\n")
    if len(lines) > max_lines:
        truncated = True
        lines = lines[-max_lines:] if from_tail else lines[:max_lines]
        text = "\n".join(lines)
    data = text.encode("utf-8")
    if len(data) > max_bytes:
        truncated = True
        data = data[-max_bytes:] if from_tail else data[:max_bytes]
        text = data.decode("utf-8", "ignore")
    if truncated:
        text += "\n\n[output truncated]"
    return text


@dataclass
class ToolContext:
    """What each tool needs to interact with the session.

    Tools do NOT know the interface: if they need to communicate something to the UI
    (``todowrite``, ``task``), their ``execute`` is a *generator* that ``yield``s
    core events (see ``minicode.events``); the ``Agent`` forwards them.
    """

    config: Any
    session: Any
    # Generator: ``yield``s the subagent's events and ``return``s its final report.
    # The ``task`` tool consumes it with ``yield from``.
    spawn_subagent: Callable[[str, str], Iterator[Any]]


class Tool:
    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}}
    read_only: bool = False

    def execute(
        self, args: dict, ctx: ToolContext
    ) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def schema(self) -> dict:
        """Tool format that the OpenAI-style API understands."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
