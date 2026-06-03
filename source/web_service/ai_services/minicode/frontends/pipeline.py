"""Adaptador del *Agent integration contract* de Pequeroku (Django Channels).

Es un frontend más del core de minicode: en vez de pintar en una terminal, mapea el
stream de eventos del agente a los callbacks async que espera el ``AIConsumer``.
Expone los DOS únicos símbolos que el consumer importa:

    from ai_services.minicode.frontends.pipeline import run_pipeline, agent

- ``run_pipeline(...)``  — corre UN turno completo y devuelve ``(messages, TokenUsage)``.
- ``agent``             — objeto con ``.model`` (solo para el log de uso).

PUENTE SÍNCRONO ↔ ASÍNCRONO
El core de minicode es síncrono (cliente OpenAI sync, tools que hacen HTTP a la VM),
y el contrato es async. Corremos el generador del agente en un hilo
(``asyncio.to_thread``) — ahí vive TODO lo bloqueante (OpenAI, llamadas a la VM,
ORM de Django) — y por cada evento agendamos su callback async en el event loop con
``run_coroutine_threadsafe`` y esperamos: así nada bloquea el loop de Channels y se
respeta el orden de los eventos. Esto resuelve de raíz el bloqueo del event loop que
tenía el agente anterior.

CREDENCIALES
Se leen de la tabla ``Config`` de la DB (openai_api_key / openai_api_url /
openai_model). La lectura ocurre dentro del hilo worker, nunca en el event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..agent import Agent
from ..config import Config
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
# Tipo de uso de tokens (compatible con lo que el consumer espera:
# atributos enteros prompt_tokens / completion_tokens / total_tokens + add_usage).
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
# Credenciales / símbolo ``agent``
# --------------------------------------------------------------------------- #
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o"


def _read_ai_config() -> dict[str, str]:
    """Lee credenciales/modelo de la tabla Config (SYNC; llamar en un hilo)."""
    from internal_config.models import Config as DjangoConfig

    return DjangoConfig.get_config_values(
        ["openai_api_key", "openai_api_url", "openai_model"]
    )


class _AgentInfo:
    """Objeto ``agent`` del contrato: solo necesita ``.model`` (para el log de uso)."""

    @property
    def model(self) -> str:
        try:
            return _read_ai_config().get("openai_model") or _DEFAULT_MODEL
        except Exception:
            return _DEFAULT_MODEL


agent = _AgentInfo()


def _build_config(container_obj: Any) -> Config:
    """Construye el Config de minicode con credenciales de la DB + el container.

    SYNC (toca el ORM y atributos del container): debe ejecutarse en el hilo worker.
    """
    cfg = _read_ai_config()
    config = Config(
        api_key=cfg.get("openai_api_key") or "",
        base_url=cfg.get("openai_api_url") or _DEFAULT_BASE_URL,
        model=cfg.get("openai_model") or _DEFAULT_MODEL,
        workdir="/app",
    )
    config.container = container_obj
    return config


def _synth_command(name: str, args: dict) -> str:
    """Texto compacto para ``on_tool_call`` (el front lo pinta como contexto)."""
    if name == "bash":
        return str(args.get("command", ""))
    if name == "process":
        return f"process {args.get('action', 'status')} {args.get('job_id', '')}".strip()
    for key in ("filePath", "pattern", "path", "url", "search_query"):
        if key in args:
            return f"{name} {args[key]}"
    if name == "task":
        return f"task:{args.get('subagent_type', 'general')} {args.get('description', '')}".strip()
    if name == "todowrite":
        return f"todowrite ({len(args.get('todos', []))} items)"
    return name


def _final_messages(session: Session, fallback: str) -> list[dict]:
    """Devuelve el historial garantizando que ``messages[-1]`` sea el assistant
    final con ``content`` string NO vacío (lo exige el consumer para el log)."""
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
# El único punto de entrada del contrato
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

    session = Session()  # sin memory_path: la persistencia la hace el consumer
    # El consumer nos devuelve verbatim lo que retornamos el turno anterior
    # (formato OpenAI); Session.sanitize() repara cualquier desajuste al arrancar.
    session.messages = [m for m in (messages or []) if isinstance(m, dict)]
    session.add_user(query)

    usage = TokenUsage()

    async def _safe(callback, *call_args, **call_kwargs) -> None:
        # Callbacks best-effort: una excepción en la UI nunca debe romper el turno.
        try:
            await callback(*call_args, **call_kwargs)
        except Exception:
            pass

    def _on_loop(coro) -> None:
        # Desde el hilo worker: agenda el callback en el loop y espera (preserva orden).
        asyncio.run_coroutine_threadsafe(coro, loop).result()

    def _emit(payload: dict) -> None:
        if on_event is not None:
            _on_loop(_safe(on_event, payload))

    def drive() -> None:
        # Corre en un hilo: aquí vive todo el trabajo bloqueante (OpenAI, VM, ORM).
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
                    _emit({"type": "info", "message": event.message, "depth": event.depth})
                elif isinstance(event, Error):
                    _emit({"type": "error", "message": event.message, "depth": event.depth})
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
        except Exception as e:  # nunca tumbamos el turno: lo reportamos como texto
            err = f"Error ejecutando el agente: {e}"
            _on_loop(_safe(on_start_chunking))
            _on_loop(_safe(on_chunk, err))
            _on_loop(_safe(on_finish_chunking, err))
            session.add_assistant(err, [])

    await asyncio.to_thread(drive)

    final = session.last_assistant_text() or "(sin respuesta)"
    return _final_messages(session, final), usage
