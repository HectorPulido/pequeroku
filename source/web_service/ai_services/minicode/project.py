"""Project instructions (AGENTS.md / CLAUDE.md) loaded from the VM, once per turn.

opencode injects an ``AGENTS.md`` (Cursor-style project rules) into the system
prompt. The original minicode walked the SERVER filesystem for it, which would
leak server config, so the Pequeroku port removed it (see ``context.py``). Now the
workspace is the user's VM (``/app``), so reading ``/app/AGENTS.md`` from the VM is
both safe and correct: it is the user's own project file, and it persists with the
workspace (and is wiped on a workspace reset, like any other file under ``/app``).

``CLAUDE.md`` is supported as an alias of ``AGENTS.md`` (Claude Code compat): the
FIRST file that exists wins. Loading happens once per turn in the pipeline's worker
thread; ``build_system`` only concatenates the already-loaded string (no I/O).
"""

from __future__ import annotations

import posixpath

from .prompts import INSTRUCTIONS_HEADER

# Root-level instruction files, in precedence order. CLAUDE.md is an alias of
# AGENTS.md: the first one that exists is used (the rest are ignored).
INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md"]
MAX_DOC_CHARS = 32_000


def load_project_doc(config) -> str | None:
    """Read the project's instructions file from the VM workdir.

    Returns the file contents wrapped with its ``Instructions from: <path>``
    header (ready to append to the system prompt), or ``None`` if the project has
    no instructions file. Best-effort: any VM error yields ``None``.
    """
    from .tools.vm import client_for_config

    client, cid = client_for_config(config)
    if client is None:
        return None
    workdir = getattr(config, "workdir", "/app") or "/app"
    for name in INSTRUCTION_FILES:
        path = posixpath.join(workdir, name)
        try:
            resp = client.read_file(cid, path)
        except Exception:
            continue
        if not isinstance(resp, dict) or not resp.get("found"):
            continue
        content = (resp.get("content") or "").strip()
        if not content:
            continue
        if len(content) > MAX_DOC_CHARS:
            content = content[:MAX_DOC_CHARS] + "\n\n[instructions truncated]"
        return f"{INSTRUCTIONS_HEADER.format(path=path)}\n{content}"
    return None
