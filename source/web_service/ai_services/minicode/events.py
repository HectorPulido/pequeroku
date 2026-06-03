"""Eventos del núcleo: el ÚNICO canal de salida del core hacia el exterior.

El bucle agéntico (``Agent.run``) es un *generador*: en vez de escribir en una
terminal, hace ``yield`` de eventos tipados (estas dataclasses). Quien consume el
generador decide cómo materializarlos: una terminal (ANSI), una web (SSE/websocket)
o una API (serializar a JSON). Así el core no sabe nada de ``stdout``, colores ni
``input()`` — está totalmente desacoplado de la interfaz.

Cada evento lleva ``depth``: 0 = agente principal, >0 = anidamiento de subagentes.
Lo rellena el agente que posee ese nivel; un evento con ``depth=None`` aún no ha
sido "sellado" (lo crean ``LLM`` y la tool ``todowrite``, que no conocen el nivel)
y el agente más cercano le pone su profundidad antes de reenviarlo hacia fuera.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional


class Event:
    """Base común de todos los eventos (solo para ``isinstance`` y tipado)."""


# -- texto del asistente en streaming ------------------------------------- #
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


# -- herramientas --------------------------------------------------------- #
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


# -- subagentes ----------------------------------------------------------- #
@dataclass
class SubagentStarted(Event):
    agent_type: str
    prompt: str
    depth: Optional[int] = None


@dataclass
class SubagentFinished(Event):
    agent_type: str
    depth: Optional[int] = None


# -- mensajes sueltos del bucle ------------------------------------------- #
@dataclass
class Info(Event):
    message: str
    depth: Optional[int] = None


@dataclass
class Error(Event):
    message: str
    depth: Optional[int] = None


# -- conteo de tokens ----------------------------------------------------- #
@dataclass
class Usage(Event):
    """Uso de tokens de UN paso del modelo. El agente lo emite tras cada llamada
    al LLM (también los subagentes), así un consumidor puede sumarlos por turno."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    depth: Optional[int] = None


def event_to_dict(event: Event) -> dict:
    """Serializa un evento a un dict JSON-able (``{"type": ..., ...campos}``).

    Útil para una API/web: ``json.dumps(event_to_dict(ev))`` por cada evento
    del stream (p. ej. en Server-Sent Events o un websocket).
    """
    data = dataclasses.asdict(event)
    data["type"] = type(event).__name__
    return data
