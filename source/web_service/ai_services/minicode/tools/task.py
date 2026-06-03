"""Herramienta task: delega en un subagente.

Versión reducida de ``tool/task.ts``: crea una sesión hija con su propio bucle
agéntico y un conjunto de herramientas restringido (aislamiento de contexto y de
privilegios). La ejecución es en foreground: devuelve el reporte final del hijo.
El puente real lo aporta ``ctx.spawn_subagent`` (lo provee el ``Agent``).
"""

from __future__ import annotations

from typing import Iterator

from ..events import Event
from .base import Tool, ToolContext


class TaskTool(Tool):
    name = "task"
    description = (
        "Delegate a focused sub-task to a subagent that runs its own loop in an "
        "isolated context, and return its final report. Use subagent_type='explore' "
        "for read-only codebase investigation (keeps your context lean), or "
        "'general' for an autonomous subtask that may edit files and run commands."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "3-5 word description of the sub-task.",
            },
            "prompt": {
                "type": "string",
                "description": "Full, self-contained instructions for the subagent.",
            },
            "subagent_type": {
                "type": "string",
                "enum": ["explore", "general"],
                "description": "Which subagent to spawn.",
            },
        },
        "required": ["description", "prompt", "subagent_type"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> Iterator[Event]:
        # Generador: reenvía (con ``yield from``) los eventos del subagente en vivo
        # y devuelve su reporte final como texto para el modelo.
        agent_type = args.get("subagent_type", "general")
        if agent_type not in ("explore", "general"):
            agent_type = "general"
        report = yield from ctx.spawn_subagent(agent_type, args["prompt"])
        return f'<task subagent="{agent_type}">\n{report}\n</task>'
