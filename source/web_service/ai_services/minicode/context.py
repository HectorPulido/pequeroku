"""Ensamblado del contexto de sistema en cada vuelta del bucle.

Adaptación Pequeroku: el agente trabaja sobre una VM remota (Debian), NO sobre el
filesystem del servidor de Django. Por eso el bloque ``<env>`` describe la VM y los
lookups NO se hacen sobre el FS del servidor (el minicode original leía
AGENTS.md/CLAUDE.md subiendo por el árbol local e incluso ``~/.claude/CLAUDE.md``,
lo que filtraría config del servidor). En su lugar, el contexto de proyecto se lee
de la VM del usuario (``/app/AGENTS.md``) y los skills de ``/app/.pequenin/skills``;
ambos los carga el pipeline UNA vez por turno y los deja en el ``Config``.

``build_system`` se llama en CADA vuelta del bucle, así que se mantiene barato: solo
strings, sin I/O ni round-trips a la VM (lee ``config.project_doc`` / ``config.skills``
ya cargados).
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
        "Platform: linux (Debian VM)\n"
        f"Today's date: {datetime.date.today().isoformat()}\n"
        "Sandbox: a per-user VM in Pequeroku; you are root and act without confirmation.\n"
        "</env>"
    )


def build_system(config: Config, agent_type: str = "build") -> str:
    base = SUBAGENT_PROMPTS.get(agent_type, SYSTEM_PROMPT)
    parts = [base, _env_block(config)]
    # Skills: solo para los agentes que tienen la tool `skill` (build/general);
    # listarlos en `explore` (read-only, sin la tool) sería ruido inactivo.
    if agent_type in ("build", "general"):
        block = skills_index_block(getattr(config, "skills", []) or [])
        if block:
            parts.append(block)
    # Instrucciones del proyecto (AGENTS.md/CLAUDE.md): aplican a cualquier agente.
    doc = getattr(config, "project_doc", None)
    if doc:
        parts.append(doc)
    return "\n\n".join(parts)
