"""Modelo común de una herramienta + truncado de salida.

Equivale a ``tool/tool.ts`` y ``tool/truncate.ts`` de opencode: una interfaz
uniforme (``Tool``), el ``ToolContext`` que recibe ``execute``, y el truncado
automático para que una salida enorme no reviente la ventana de contexto.
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
    """Recorta por cabeza (por defecto) o por cola (``from_tail``, p. ej. shell)."""
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
        text += "\n\n[salida truncada]"
    return text


@dataclass
class ToolContext:
    """Lo que cada herramienta necesita para interactuar con la sesión.

    Las tools NO conocen la interfaz: si necesitan comunicar algo a la UI
    (``todowrite``, ``task``), su ``execute`` es un *generador* que hace ``yield``
    de eventos del core (ver ``minicode.events``); el ``Agent`` los reenvía.
    """

    config: Any
    session: Any
    # Generador: hace ``yield`` de los eventos del subagente y ``return`` de su
    # reporte final. La tool ``task`` lo consume con ``yield from``.
    spawn_subagent: Callable[[str, str], Iterator[Any]]


class Tool:
    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}}
    read_only: bool = False

    def execute(self, args: dict, ctx: ToolContext) -> str:  # pragma: no cover - interfaz
        raise NotImplementedError

    @property
    def schema(self) -> dict:
        """Formato de herramienta que entiende la API estilo OpenAI."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
