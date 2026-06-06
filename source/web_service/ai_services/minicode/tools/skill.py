"""skill tool: load a reusable skill (SKILL.md) ON DEMAND.

opencode-compatible progressive disclosure: the system prompt lists the available
skills (name + description + location); this tool injects the FULL body of one
skill when the model decides a task matches it. Skills live in the VM under
``/app/.pequenin/skills/<name>/`` — discovery + loading live in ``minicode.skills``.
"""

from __future__ import annotations

from .base import Tool, ToolContext
from ..prompts import SKILL_TOOL_DESCRIPTION


class SkillTool(Tool):
    name = "skill"
    read_only = True
    description = SKILL_TOOL_DESCRIPTION
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Name of the skill to load. Must match one of the skills "
                    "listed in your system prompt."
                ),
            },
        },
        "required": ["name"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        from ..skills import load_skill_body
        from . import vm

        name = args.get("name", "")
        output = load_skill_body(ctx.config, name)
        try:  # best-effort audit, mirrors the other VM-backed tools
            _, cid = vm.get_client(ctx)
            vm.audit("read_file", cid, "Load skill", {"skill": name})
        except Exception:
            pass
        return output
