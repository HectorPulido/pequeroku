"""Tool registry and selection by agent type.

The main agent (``build``) has all the tools. Subagents get a less-privileged
subset (isolation), and never ``task`` (to avoid runaway recursion).

Pequeroku adaptation: the file/shell tools operate on the remote VM; ``process``
(background job control) and the internet ones (``search_on_internet`` /
``read_from_internet``) are added.
"""

from __future__ import annotations

from .base import Tool, ToolContext, truncate
from .files import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from .internet import WebReadTool, WebSearchTool
from .memory import (
    DeleteMemoryTool,
    EditMemoryTool,
    ReadMemoryTool,
    SaveMemoryTool,
)
from .shell import BashTool, ProcessTool
from .skill import SkillTool
from .task import TaskTool
from .todo import TodoWriteTool

# Memory CRUD (save/read/edit/delete). Read-only agents get only ReadMemoryTool.
MEMORY = [SaveMemoryTool, ReadMemoryTool, EditMemoryTool, DeleteMemoryTool]

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
    *MEMORY,
    SkillTool,
    TaskTool,
]


def tools_for(agent_type: str = "build") -> list[Tool]:
    if agent_type == "explore":
        # Read-only investigator: it may recall memories but never mutate them.
        classes = [
            ReadTool,
            GlobTool,
            GrepTool,
            WebSearchTool,
            WebReadTool,
            ReadMemoryTool,
        ]
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
            SkillTool,
            *MEMORY,
        ]
    else:  # build (main agent)
        classes = ALL
    return [c() for c in classes]


__all__ = ["Tool", "ToolContext", "truncate", "tools_for", "ALL"]
