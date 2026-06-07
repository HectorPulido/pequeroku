"""task tool: delegates to a subagent.

A trimmed-down version of ``tool/task.ts``: it creates a child session with its own
agentic loop and a restricted toolset (context and privilege isolation). Execution
is foreground: it returns the child's final report. The actual bridge is provided by
``ctx.spawn_subagent`` (supplied by the ``Agent``).
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
        # Generator: forwards (with ``yield from``) the subagent's live events and
        # returns its final report as text for the model.
        agent_type = args.get("subagent_type", "general")
        if agent_type not in ("explore", "general"):
            agent_type = "general"
        report = yield from ctx.spawn_subagent(agent_type, args["prompt"])
        return f'<task subagent="{agent_type}">\n{report}\n</task>'
