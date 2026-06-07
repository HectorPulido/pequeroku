"""Agent configuration.

Pequeroku adaptation: the agent does NOT operate on the local filesystem but on a
remote VM (via ``VMServiceClient``). The credentials/model are injected by the
Django wrapper (``frontends.pipeline``), which reads them from the DB's ``Config``
table; the ``container`` is carried here so the tools can talk to their VM.

It remains compatible with any OpenAI-style endpoint by changing ``base_url``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependencies). Does not override already-set variables."""
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
    # In Pequeroku the workspace is the user's VM, anchored at /app.
    workdir: str = "/app"
    # The workdir is always the primary area. By default reading/editing OUTSIDE it
    # IS allowed when the task requires it; restrict_to_workdir=True forbids it (hard wall).
    restrict_to_workdir: bool = False
    # Container (vm_manager.models.Container) the tools operate on. Set by the Django
    # wrapper; subagents inherit the same object (same VM).
    container: Any = None
    # Default timeout (s) for foreground commands via execute_sh.
    foreground_timeout: int = 25
    # ---- Per-turn project context (loaded by the pipeline ONCE, in the worker
    # thread, reading from the VM; ``build_system`` only concatenates, no I/O). ----
    # Contents of AGENTS.md/CLAUDE.md already wrapped with its "Instructions from:"
    # header, or None if the project has no instructions file.
    project_doc: str | None = None
    # Skills discovered for this turn (list[skills.Skill]). Loosely typed to avoid
    # importing the skills module here (subagents inherit the same Config).
    skills: list = field(default_factory=list)
    # MCP (remote) tools discovered for this turn (list[mcp.McpTool], with their HTTP
    # client already connected). The Agent adds them to its toolset; build/general
    # subagents inherit the same Config and therefore the same tools.
    mcp_tools: list = field(default_factory=list)
    # Custom tools (defined by the user under /app/.pequenin/tools/, executed in the
    # VM) discovered for this turn (list[custom_tools.CustomTool]). Same treatment as
    # mcp_tools: they are added to the build/general toolset.
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
