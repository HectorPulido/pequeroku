"""Adapter for Pequeroku's *Agent integration contract* (Django Channels).

It is just another frontend of the minicode core: instead of painting to a
terminal, it maps the agent's event stream to the async callbacks the
``AIConsumer`` expects. The symbols the consumer imports:

    from ai_services.minicode.frontends.pipeline import (
        run_pipeline, agent, TokenUsage, _synth_command, _cap,
    )

- ``run_pipeline(...)``  — runs ONE full turn and returns ``(messages, TokenUsage)``.
- ``agent``             — object with ``.model`` (only for the usage log).
- ``_synth_command`` / ``_cap`` — shared so history replay (``send_history``) can
  rebuild the persisted tool timeline using the SAME command synthesis and output
  cap as the live event stream below, keeping live and replayed steps identical.

SYNC ↔ ASYNC BRIDGE
The minicode core is synchronous (sync OpenAI client, tools that do HTTP to the
VM), and the contract is async. We run the agent's generator in a thread
(``asyncio.to_thread``) — that is where ALL the blocking work lives (OpenAI, VM
calls, Django ORM) — and for each event we schedule its async callback on the event
loop with ``run_coroutine_threadsafe`` and wait: this way nothing blocks the
Channels loop and event order is preserved. This fundamentally fixes the event-loop
blocking the previous agent had.

CREDENTIALS
Read from the DB's ``Config`` table (openai_api_key / openai_api_url /
openai_model). The read happens inside the worker thread, never on the event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..agent import Agent
from ..config import Config
from ..custom_tools import discover_custom_tools
from ..mcp import discover_mcp_tools
from ..project import load_project_doc
from ..skills import discover_skills
from ..events import (
    AssistantTextDelta,
    AssistantTextEnd,
    AssistantTextStart,
    Error,
    Info,
    SubagentFinished,
    SubagentStarted,
    ToolCallStarted,
    ToolResult,
    TodosUpdated,
    Usage,
)
from ..llm import LLM
from ..session import Session

# Cap for free-form text fields forwarded to the UI (tool output, subagent prompt),
# so a huge command output doesn't blow up the websocket frame.
_EVENT_TEXT_CAP = 4000


def _cap(text: object, limit: int = _EVENT_TEXT_CAP) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= limit else s[:limit] + "\n…[truncated]"


# --------------------------------------------------------------------------- #
# Token-usage type (compatible with what the consumer expects: integer
# attributes prompt_tokens / completion_tokens / total_tokens + add_usage).
# --------------------------------------------------------------------------- #
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add_usage(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.total_tokens + other.total_tokens,
        )


# --------------------------------------------------------------------------- #
# Credentials / the ``agent`` symbol
# --------------------------------------------------------------------------- #
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o"


def _read_ai_config() -> dict[str, str]:
    """Read credentials/model from the Config table (SYNC; call from a thread)."""
    from internal_config.models import Config as DjangoConfig

    return DjangoConfig.get_config_values(
        ["openai_api_key", "openai_api_url", "openai_model"]
    )


class _AgentInfo:
    """The contract's ``agent`` object: it only needs ``.model`` (for the usage log)."""

    @property
    def model(self) -> str:
        try:
            return _read_ai_config().get("openai_model") or _DEFAULT_MODEL
        except Exception:
            return _DEFAULT_MODEL


agent = _AgentInfo()


def _build_config(container_obj: Any) -> Config:
    """Build minicode's Config with DB credentials + the container.

    SYNC (touches the ORM and container attributes): must run in the worker thread.
    It also loads the VM's project context (AGENTS.md and skills) ONCE per turn;
    ``build_system`` then only concatenates what is already loaded (no I/O per step).
    """
    cfg = _read_ai_config()
    config = Config(
        api_key=cfg.get("openai_api_key") or "",
        base_url=cfg.get("openai_api_url") or _DEFAULT_BASE_URL,
        model=cfg.get("openai_model") or _DEFAULT_MODEL,
        workdir="/app",
    )
    config.container = container_obj
    # Project context (best-effort: a VM failure must never bring the turn down).
    try:
        config.project_doc = load_project_doc(config)
    except Exception:
        config.project_doc = None
    try:
        config.skills = discover_skills(config)
    except Exception:
        config.skills = []
    # MCP: connect to remote servers declared in /app/.pequenin/mcp.json and expose
    # their tools for this turn (best-effort; a bad server never breaks the turn).
    try:
        config.mcp_tools = discover_mcp_tools(config)
    except Exception:
        config.mcp_tools = []
    # Custom tools defined in /app/.pequenin/tools/ (run inside the VM).
    try:
        config.custom_tools = discover_custom_tools(config)
    except Exception:
        config.custom_tools = []
    return config


def _synth_command(name: str, args: dict) -> str:
    """Compact text for ``on_tool_call`` (the frontend renders it as context)."""
    if name == "bash":
        return str(args.get("command", ""))
    if name == "process":
        return (
            f"process {args.get('action', 'status')} {args.get('job_id', '')}".strip()
        )
    if name == "read_memories":
        return "read_memories"
    if name in ("save_memory", "edit_memory", "delete_memory"):
        return f"{name} {args.get('id', '')}".strip()
    for key in ("filePath", "pattern", "path", "url", "search_query"):
        if key in args:
            return f"{name} {args[key]}"
    if name == "task":
        return f"task:{args.get('subagent_type', 'general')} {args.get('description', '')}".strip()
    if name == "todowrite":
        return f"todowrite ({len(args.get('todos', []))} items)"
    return name


def _final_messages(session: Session, fallback: str) -> list[dict]:
    """Return the history, guaranteeing that ``messages[-1]`` is the final assistant
    with a NON-empty string ``content`` (the consumer requires it for the log)."""
    out = list(session.messages)
    last = out[-1] if out else None
    ok = (
        last is not None
        and last.get("role") == "assistant"
        and isinstance(last.get("content"), str)
        and last["content"].strip()
        and not last.get("tool_calls")
    )
    if not ok:
        out.append({"role": "assistant", "content": fallback})
    return out


# --------------------------------------------------------------------------- #
# The contract's single entry point
# --------------------------------------------------------------------------- #
async def run_pipeline(
    query: str,
    messages: list[dict],
    container_obj: Any,
    on_chunk: Callable[[str], Awaitable[None]],
    on_tool_call: Callable[..., Awaitable[None]],
    on_start_chunking: Callable[[], Awaitable[None]],
    on_finish_chunking: Callable[[str], Awaitable[None]],
    on_event: Callable[[dict], Awaitable[None]] | None = None,
) -> tuple[list[dict], TokenUsage]:
    """Run one agent turn.

    ``on_event`` (optional) receives a structured dict for every core event —
    tool calls *with their args*, tool *results*, todo updates, subagent
    start/finish, info/error notices and per-step token usage. It exposes what
    the agent is doing internally (beyond the streamed answer text) so a UI can
    render it; callers that don't care can omit it.
    """
    loop = asyncio.get_running_loop()

    session = Session()  # no memory_path: persistence is handled by the consumer
    # The consumer hands us back verbatim what we returned on the previous turn
    # (OpenAI format); Session.sanitize() repairs any mismatch on startup.
    session.messages = [m for m in (messages or []) if isinstance(m, dict)]
    session.add_user(query)

    usage = TokenUsage()

    async def _safe(callback, *call_args, **call_kwargs) -> None:
        # Best-effort callbacks: an exception in the UI must never break the turn.
        try:
            await callback(*call_args, **call_kwargs)
        except Exception:
            pass

    def _on_loop(coro) -> None:
        # From the worker thread: schedule the callback on the loop and wait (preserves order).
        asyncio.run_coroutine_threadsafe(coro, loop).result()

    def _emit(payload: dict) -> None:
        if on_event is not None:
            _on_loop(_safe(on_event, payload))

    def drive() -> None:
        # Runs in a thread: this is where all the blocking work lives (OpenAI, VM, ORM).
        config = _build_config(container_obj)
        llm = LLM(config)
        block: list[str] = []
        try:
            for event in Agent(config, llm, session=session).run():
                if isinstance(event, AssistantTextStart):
                    block = []
                    _on_loop(_safe(on_start_chunking))
                elif isinstance(event, AssistantTextDelta):
                    block.append(event.text)
                    _on_loop(_safe(on_chunk, event.text))
                elif isinstance(event, AssistantTextEnd):
                    _on_loop(_safe(on_finish_chunking, "".join(block)))
                elif isinstance(event, ToolCallStarted):
                    command = _synth_command(event.name, event.args or {})
                    _on_loop(_safe(on_tool_call, event.name, command=command))
                    _emit(
                        {
                            "type": "tool_call",
                            "name": event.name,
                            "args": event.args or {},
                            "command": command,
                            "depth": event.depth,
                        }
                    )
                elif isinstance(event, ToolResult):
                    _emit(
                        {
                            "type": "tool_result",
                            "name": event.name,
                            "output": _cap(event.output),
                            "depth": event.depth,
                        }
                    )
                elif isinstance(event, TodosUpdated):
                    _emit({"type": "todos", "todos": event.todos, "depth": event.depth})
                elif isinstance(event, SubagentStarted):
                    _emit(
                        {
                            "type": "subagent_started",
                            "agent_type": event.agent_type,
                            "prompt": _cap(event.prompt, 1000),
                            "depth": event.depth,
                        }
                    )
                elif isinstance(event, SubagentFinished):
                    _emit(
                        {
                            "type": "subagent_finished",
                            "agent_type": event.agent_type,
                            "depth": event.depth,
                        }
                    )
                elif isinstance(event, Info):
                    _emit(
                        {"type": "info", "message": event.message, "depth": event.depth}
                    )
                elif isinstance(event, Error):
                    _emit(
                        {
                            "type": "error",
                            "message": event.message,
                            "depth": event.depth,
                        }
                    )
                elif isinstance(event, Usage):
                    usage.prompt_tokens += event.prompt_tokens
                    usage.completion_tokens += event.completion_tokens
                    usage.total_tokens += event.total_tokens
                    _emit(
                        {
                            "type": "usage",
                            "prompt_tokens": event.prompt_tokens,
                            "completion_tokens": event.completion_tokens,
                            "total_tokens": event.total_tokens,
                            "depth": event.depth,
                        }
                    )
        except Exception as e:  # we never crash the turn: we report it as text
            err = f"Error running the agent: {e}"
            _on_loop(_safe(on_start_chunking))
            _on_loop(_safe(on_chunk, err))
            _on_loop(_safe(on_finish_chunking, err))
            session.add_assistant(err, [])

    await asyncio.to_thread(drive)

    final = session.last_assistant_text() or "(no response)"
    return _final_messages(session, final), usage
