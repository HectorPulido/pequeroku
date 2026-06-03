"""Ensamblado del contexto de sistema en cada vuelta del bucle.

Adaptación Pequeroku: el agente trabaja sobre una VM remota (Debian), NO sobre el
filesystem del servidor de Django. Por eso el bloque ``<env>`` describe la VM y NO
se hacen lookups en el FS local (el minicode original leía AGENTS.md/CLAUDE.md
subiendo por el árbol e incluso ``~/.claude/CLAUDE.md`` — aquí eso filtraría la
config del servidor en el prompt, así que se elimina).

``build_system`` se llama en CADA vuelta del bucle, así que se mantiene barato: solo
strings, sin I/O ni round-trips a la VM.
"""
from __future__ import annotations

import datetime

from .config import Config
from .prompts import SYSTEM_PROMPT, SUBAGENT_PROMPTS


def _env_block(config: Config) -> str:
    workdir = getattr(config, "workdir", "/app") or "/app"
    return (
        "<env>\n"
        f"Working directory: {workdir}\n"
        "Platform: linux (Debian VM)\n"
        f"Today's date: {datetime.date.today().isoformat()}\n"
        "Sandbox: a per-user VM in Pequeroku; you are root and act without confirmation.\n"
        "</env>"
    )


def build_system(config: Config, agent_type: str = "build") -> str:
    base = SUBAGENT_PROMPTS.get(agent_type, SYSTEM_PROMPT)
    return "\n\n".join([base, _env_block(config)])
