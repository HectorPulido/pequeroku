"""Configuración del agente.

Adaptación Pequeroku: el agente NO opera sobre el filesystem local sino sobre una
VM remota (vía ``VMServiceClient``). Las credenciales/modelo las inyecta el wrapper
de Django (``frontends.pipeline``) leyéndolas de la tabla ``Config`` de la DB; el
``container`` se transporta aquí para que las tools puedan hablar con su VM.

Sigue siendo compatible con cualquier endpoint estilo OpenAI cambiando ``base_url``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_dotenv(path: str = ".env") -> None:
    """Cargador .env mínimo (sin dependencias). No pisa variables ya definidas."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    api_key: str
    base_url: str
    model: str
    max_steps: int = 50
    temperature: float | None = None
    max_output_tokens: int | None = None
    # En Pequeroku el área de trabajo es la VM del usuario, anclada en /app.
    workdir: str = "/app"
    # El workdir es siempre el área principal. Por defecto SÍ se permite leer/editar
    # fuera de él si la tarea lo requiere; con restrict_to_workdir=True se prohíbe (muro duro).
    restrict_to_workdir: bool = False
    # Container (vm_manager.models.Container) sobre el que operan las tools. Lo fija
    # el wrapper de Django; los subagentes heredan el mismo objeto (misma VM).
    container: Any = None
    # Timeout (s) por defecto para comandos foreground vía execute_sh.
    foreground_timeout: int = 25
    # ---- Contexto de proyecto por turno (lo carga el pipeline UNA vez, en el hilo
    # worker, leyendo de la VM; ``build_system`` solo concatena, sin I/O). ----
    # Contenido de AGENTS.md/CLAUDE.md ya envuelto con su encabezado "Instructions
    # from:", o None si el proyecto no tiene archivo de instrucciones.
    project_doc: str | None = None
    # Skills descubiertos para este turno (list[skills.Skill]). Tipado laxo para no
    # importar el módulo skills aquí (los subagentes heredan el mismo Config).
    skills: list = field(default_factory=list)
    # Tools MCP (remotas) descubiertas para este turno (list[mcp.McpTool], ya con su
    # cliente HTTP conectado). El Agent las añade a su toolset; los subagentes
    # build/general heredan el mismo Config y, por tanto, las mismas tools.
    mcp_tools: list = field(default_factory=list)
    # Custom tools (definidas por el usuario en /app/.pequenin/tools/, ejecutadas en
    # la VM) descubiertas para este turno (list[custom_tools.CustomTool]). Mismo
    # tratamiento que mcp_tools: se añaden al toolset de build/general.
    custom_tools: list = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        temp = os.environ.get("MINICODE_TEMPERATURE")
        max_tokens = os.environ.get("MINICODE_MAX_TOKENS")
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY")
            or os.environ.get("MINICODE_API_KEY")
            or "",
            base_url=os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("MINICODE_BASE_URL")
            or "https://api.openai.com/v1",
            model=os.environ.get("MINICODE_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "gpt-4o",
            max_steps=int(os.environ.get("MINICODE_MAX_STEPS", "50")),
            temperature=float(temp) if temp else None,
            max_output_tokens=int(max_tokens) if max_tokens else None,
            restrict_to_workdir=os.environ.get("MINICODE_RESTRICT_WORKDIR", "").lower()
            in ("1", "true", "yes"),
        )
