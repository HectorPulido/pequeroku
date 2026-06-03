"""Herramienta todowrite: lista de tareas que el modelo gestiona para planificar.

Es clave para inducir planificación explícita (el prompt anima a usarla mucho).
La lista vive en la sesión y se re-renderiza al actualizarse.
"""
from __future__ import annotations

from typing import Iterator

from ..events import Event, TodosUpdated
from .base import Tool, ToolContext

_MARK = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}


class TodoWriteTool(Tool):
    name = "todowrite"
    description = (
        "Create or update the structured task list. Use it frequently to plan and "
        "track multi-step work; mark items in_progress/completed as you go. Pass the "
        "ENTIRE list every time (it replaces the previous one)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The full task list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> Iterator[Event]:
        # Generador: emite la lista actualizada como evento y devuelve el resumen
        # de texto que verá el modelo (vía ``return``, capturado por el Agent).
        todos = args.get("todos", []) or []
        ctx.session.todos = todos
        yield TodosUpdated(todos=todos)
        lines = [f"{_MARK.get(t.get('status'), '[ ]')} {t.get('content', '')}" for t in todos]
        return "Lista de tareas actualizada:\n" + "\n".join(lines)
