"""Assembling the system context on each turn of the loop.

Pequeroku adaptation: the agent works on a remote VM (Debian), NOT on the Django
server's filesystem. That is why the ``<env>`` block describes the VM and the
lookups are NOT done against the server FS (the original minicode read
AGENTS.md/CLAUDE.md by walking up the local tree and even ``~/.claude/CLAUDE.md``,
which would leak server config). Instead, the project context is read from the
user's VM (``/app/AGENTS.md``) and the skills from ``/app/.pequenin/skills``; both
are loaded by the pipeline ONCE per turn and stashed on the ``Config``.

``build_system`` is called on EVERY turn of the loop, so it stays cheap: only
strings, no I/O or round-trips to the VM (it reads the already-loaded
``config.project_doc`` / ``config.skills``).
"""

from __future__ import annotations

import datetime

from .config import Config
from .prompts import SYSTEM_PROMPT, SUBAGENT_PROMPTS
from .skills import skills_index_block


def _env_block(config: Config) -> str:
    workdir = getattr(config, "workdir", "/app") or "/app"
    return (
        "<env>\n"
        f"Working directory: {workdir}\n"
        "Platform: linux (Debian 12 VM)\n"
        f"Today's date: {datetime.date.today().isoformat()}\n"
        "Sandbox: a per-user VM in Pequeroku; you are root and act without confirmation.\n"
        "Preinstalled baseline: python3 + pip3, git, curl, ca-certificates, "
        "python3-venv, python3-dev, build-essential (gcc/make). Assume these exist; "
        "for anything else (node, go, docker, postgres, a database server, ...) "
        "verify with `command -v <tool>` and apt-install it if missing — do not "
        "discover a missing tool by letting a build fail. (Older VM images may lack "
        "part of this baseline; a quick `command -v` settles it.)\n"
        "</env>"
    )


def build_system(config: Config, agent_type: str = "build") -> str:
    base = SUBAGENT_PROMPTS.get(agent_type, SYSTEM_PROMPT)
    parts = [base, _env_block(config)]
    # Skills: only for agents that have the `skill` tool (build/general); listing
    # them in `explore` (read-only, without the tool) would be inert noise.
    if agent_type in ("build", "general"):
        block = skills_index_block(getattr(config, "skills", []) or [])
        if block:
            parts.append(block)
    # Project instructions (AGENTS.md/CLAUDE.md): they apply to any agent.
    doc = getattr(config, "project_doc", None)
    if doc:
        parts.append(doc)
    return "\n\n".join(parts)
