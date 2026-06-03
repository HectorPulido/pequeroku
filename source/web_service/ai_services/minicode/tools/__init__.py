"""Registro de herramientas y selección por tipo de agente.

El agente principal (``build``) tiene todas las herramientas. Los subagentes
reciben un subconjunto con menos privilegios (aislamiento), y nunca ``task``
(para evitar recursión descontrolada).

Adaptación Pequeroku: las tools de archivos/shell operan sobre la VM remota; se
añaden ``process`` (control de jobs en background) y las de internet
(``search_on_internet`` / ``read_from_internet``).
"""

from __future__ import annotations

from .base import Tool, ToolContext, truncate
from .files import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from .internet import WebReadTool, WebSearchTool
from .shell import BashTool, ProcessTool
from .task import TaskTool
from .todo import TodoWriteTool

ALL = [
    ReadTool,
    WriteTool,
    EditTool,
    GlobTool,
    GrepTool,
    BashTool,
    ProcessTool,
    WebSearchTool,
    WebReadTool,
    TodoWriteTool,
    TaskTool,
]


def tools_for(agent_type: str = "build") -> list[Tool]:
    if agent_type == "explore":
        classes = [ReadTool, GlobTool, GrepTool, WebSearchTool, WebReadTool]
    elif agent_type == "general":
        classes = [
            ReadTool,
            WriteTool,
            EditTool,
            GlobTool,
            GrepTool,
            BashTool,
            ProcessTool,
            WebSearchTool,
            WebReadTool,
        ]
    else:  # build (agente principal)
        classes = ALL
    return [c() for c in classes]


__all__ = ["Tool", "ToolContext", "truncate", "tools_for", "ALL"]
