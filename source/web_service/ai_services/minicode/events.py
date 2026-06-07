"""Core events: the ONLY output channel from the core to the outside world.

The agentic loop (``Agent.run``) is a *generator*: instead of writing to a
terminal, it ``yield``s typed events (these dataclasses). Whoever consumes the
generator decides how to materialize them: a terminal (ANSI), a web app
(SSE/websocket) or an API (serialize to JSON). This way the core knows nothing
about ``stdout``, colors or ``input()`` — it is fully decoupled from the interface.

Each event carries ``depth``: 0 = main agent, >0 = subagent nesting. It is filled
in by the agent that owns that level; an event with ``depth=None`` has not been
"sealed" yet (created by ``LLM`` and the ``todowrite`` tool, which don't know the
level) and the nearest agent stamps its depth before forwarding it outward.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional


class Event:
    """Common base of all events (only for ``isinstance`` and typing)."""


# -- streaming assistant text --------------------------------------------- #
@dataclass
class AssistantTextStart(Event):
    depth: Optional[int] = None


@dataclass
class AssistantTextDelta(Event):
    text: str
    depth: Optional[int] = None


@dataclass
class AssistantTextEnd(Event):
    depth: Optional[int] = None


# -- tools ---------------------------------------------------------------- #
@dataclass
class ToolCallStarted(Event):
    name: str
    args: dict
    depth: Optional[int] = None


@dataclass
class ToolResult(Event):
    name: str
    output: str
    depth: Optional[int] = None


@dataclass
class TodosUpdated(Event):
    todos: list = field(default_factory=list)
    depth: Optional[int] = None


# -- subagents ------------------------------------------------------------ #
@dataclass
class SubagentStarted(Event):
    agent_type: str
    prompt: str
    depth: Optional[int] = None


@dataclass
class SubagentFinished(Event):
    agent_type: str
    depth: Optional[int] = None


# -- one-off loop messages ------------------------------------------------ #
@dataclass
class Info(Event):
    message: str
    depth: Optional[int] = None


@dataclass
class Error(Event):
    message: str
    depth: Optional[int] = None


# -- token usage ---------------------------------------------------------- #
@dataclass
class Usage(Event):
    """Token usage for ONE model step. The agent emits it after each LLM call
    (subagents too), so a consumer can sum them per turn."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    depth: Optional[int] = None


def event_to_dict(event: Event) -> dict:
    """Serialize an event to a JSON-able dict (``{"type": ..., ...fields}``).

    Useful for an API/web: ``json.dumps(event_to_dict(ev))`` for each event in the
    stream (e.g. in Server-Sent Events or a websocket).
    """
    data = dataclasses.asdict(event)
    data["type"] = type(event).__name__
    return data
