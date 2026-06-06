"""Skills — reusable instructions loaded ON DEMAND (opencode-compatible).

A skill is a directory under ``/app/.pequenin/skills/<name>/`` containing a
``SKILL.md`` with YAML frontmatter (``name`` + ``description`` required) and a
markdown body (it may bundle ``scripts/``, ``reference/``, ... next to it).

Progressive disclosure (the whole point): skill bodies are NOT loaded at startup.
The system prompt lists only ``name`` + ``description`` + ``location`` of each
skill (cheap); the model loads ONE skill's full body when a task matches it, by
calling the ``skill`` tool (see ``tools/skill.py``).

Everything is read from the VM (per our design: per-VM, persists with the
workspace, wiped on reset). Discovery runs once per turn in the pipeline worker
thread and is cached on ``Config.skills``; ``build_system`` only formats it.
"""

from __future__ import annotations

import pathlib
import posixpath
import re
from dataclasses import dataclass

from vm_manager.vm_client import VMPaths

from .prompts import SKILLS_PREAMBLE, SKILL_CONTENT_BASEDIR

SKILLS_DIR = "/app/.pequenin/skills"
# opencode's skill-name rule: lowercase alphanumerics joined by single hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_NAME_CHARS = 64
_MAX_DESC_CHARS = 1024
_MAX_FILES_SAMPLED = 10
_MAX_BODY_CHARS = 32_000


@dataclass
class Skill:
    name: str
    description: str
    # Location shown in the index: a VM path for project skills, or
    # ``builtin:<name>`` for built-ins shipped with the server.
    path: str
    base_dir: str  # VM dir for project skills; "" for built-ins
    source: str = "project"  # "project" | "builtin"
    body: str | None = None  # preloaded body for built-ins (None = read on demand)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into ``(frontmatter, body)``.

    Minimal, dependency-free parser (no PyYAML): only top-level ``key: value``
    lines inside the leading ``--- ... ---`` block are read; nested lines (e.g.
    under ``metadata:``) and unknown keys are ignored — we only need ``name`` and
    ``description``. Returns ``({}, text)`` when there is no frontmatter.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw or raw[0] in (" ", "\t") or ":" not in raw:
            continue  # nested / blank / not a key:value line
        key, _, value = raw.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def _read(client, cid: str, path: str) -> str | None:
    try:
        resp = client.read_file(cid, path)
    except Exception:
        return None
    if isinstance(resp, dict) and resp.get("found"):
        return resp.get("content") or ""
    return None


_BUILTIN_DIR = pathlib.Path(__file__).resolve().parent / "builtin_skills"
_builtin_cache: "list[Skill] | None" = None


def _load_builtin_skills() -> list[Skill]:
    """Built-in skills shipped with the server — always available, project-agnostic.

    Read once from ``minicode/builtin_skills/<name>/SKILL.md`` and cached. These are
    curated PRODUCT files (not user data or server secrets), so reading the server
    filesystem here is intentional and safe — unlike the original minicode, which
    walked the server FS for the USER's AGENTS.md (that is what context.py removed).
    Built-in skills are instruction-only: their body is self-contained (no VM-side
    bundled files).
    """
    global _builtin_cache
    if _builtin_cache is not None:
        return _builtin_cache
    out: list[Skill] = []
    try:
        dirs = sorted(p for p in _BUILTIN_DIR.iterdir() if p.is_dir())
    except Exception:
        dirs = []
    for d in dirs:
        try:
            content = (d / "SKILL.md").read_text(encoding="utf-8")
        except Exception:
            continue
        meta, body = _parse_frontmatter(content)
        name = (meta.get("name") or "").strip()
        desc = " ".join((meta.get("description") or "").split())
        if not name or not _NAME_RE.match(name) or len(name) > _MAX_NAME_CHARS:
            continue
        if name != d.name:
            continue
        if not desc or len(desc) > _MAX_DESC_CHARS:
            continue
        out.append(
            Skill(
                name=name,
                description=desc,
                path=f"builtin:{name}",
                base_dir="",
                source="builtin",
                body=body,
            )
        )
    _builtin_cache = out
    return out


def discover_skills(config) -> list[Skill]:
    """Built-in skills (always) + project skills under ``/app/.pequenin/skills``.

    Runs once per turn. Project skills OVERRIDE built-ins of the same name (a
    workspace can shadow a built-in). Best-effort: a VM error, a missing directory or
    an invalid ``SKILL.md`` never raises — invalid skills are skipped, and the
    built-ins are still returned even when the VM is unreachable.
    """
    # Built-ins first; project skills (below) override them by name.
    skills: dict[str, Skill] = {s.name: s for s in _load_builtin_skills()}

    from .tools.vm import client_for_config

    client, cid = client_for_config(config)
    if client is not None:
        try:
            entries = client.list_dirs(cid, VMPaths(paths=[SKILLS_DIR], depth=2))
        except Exception:
            entries = []
        if isinstance(entries, list):
            for e in entries:
                if not isinstance(e, dict):
                    continue
                if e.get("name") != "SKILL.md" or e.get("path_type") != "file":
                    continue
                path = str(e.get("path") or "")
                if not path:
                    continue
                base_dir = posixpath.dirname(path)
                folder = posixpath.basename(base_dir)
                content = _read(client, cid, path)
                if content is None:
                    continue
                meta, _ = _parse_frontmatter(content)
                name = (meta.get("name") or "").strip()
                desc = " ".join((meta.get("description") or "").split())
                # Validation (opencode rules): name well-formed and == folder name;
                # description present and bounded. Anything off → skip the skill.
                if not name or not _NAME_RE.match(name) or len(name) > _MAX_NAME_CHARS:
                    continue
                if name != folder:
                    continue
                if not desc or len(desc) > _MAX_DESC_CHARS:
                    continue
                skills[name] = Skill(
                    name=name, description=desc, path=path, base_dir=base_dir
                )
    return sorted(skills.values(), key=lambda s: s.name)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def skills_index_block(skills: list[Skill]) -> str:
    """Verbose ``<available_skills>`` block for the system prompt.

    Lists each skill's name + description + location so the agent knows what it can
    load and where it lives. Returns ``""`` when there are no skills.
    """
    if not skills:
        return ""
    rows = []
    for s in skills:
        rows.append(
            "  <skill>\n"
            f"    <name>{_xml_escape(s.name)}</name>\n"
            f"    <description>{_xml_escape(s.description)}</description>\n"
            f"    <location>{_xml_escape(s.path)}</location>\n"
            "  </skill>"
        )
    return (
        SKILLS_PREAMBLE
        + "\n<available_skills>\n"
        + "\n".join(rows)
        + "\n</available_skills>"
    )


def load_skill_body(config, name: str) -> str:
    """Return the full SKILL.md body wrapped for injection (the ``skill`` tool).

    Validates ``name`` against the skills discovered for this turn
    (``config.skills``), reads the body from the VM, and appends a sampled list
    (≤10) of the files bundled in the skill directory.
    """
    name = (name or "").strip()
    skills = list(getattr(config, "skills", []) or [])
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        available = ", ".join(s.name for s in skills) or "(none)"
        return f"Error: unknown skill '{name}'. Available skills: {available}."

    # Built-in skills are instruction-only and preloaded from the server; no VM read,
    # no <skill_files> block (their body must be self-contained).
    if skill.source == "builtin":
        body = skill.body or ""
        if len(body) > _MAX_BODY_CHARS:
            body = body[:_MAX_BODY_CHARS] + "\n\n[skill truncated]"
        return (
            f'<skill_content name="{_xml_escape(name)}">\n'
            f"# Skill: {name}\n\n"
            f"{body}\n"
            f"</skill_content>"
        )

    from .tools.vm import client_for_config

    client, cid = client_for_config(config)
    if client is None:
        return "Error: no VM is bound to this session."
    content = _read(client, cid, skill.path)
    if content is None:
        return f"Error: could not read skill '{name}' at {skill.path}."
    _, body = _parse_frontmatter(content)
    body = body or content
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n\n[skill truncated]"

    files: list[str] = []
    try:
        entries = client.list_dirs(cid, VMPaths(paths=[skill.base_dir], depth=2))
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("path_type") == "file":
                    p = str(e.get("path") or "")
                    if p:
                        files.append(p)
    except Exception:
        pass
    files = sorted(set(files))[:_MAX_FILES_SAMPLED]
    files_block = "\n".join(f"<file>{p}</file>" for p in files)

    return (
        f'<skill_content name="{_xml_escape(name)}">\n'
        f"# Skill: {name}\n\n"
        f"{body}\n\n"
        f"{SKILL_CONTENT_BASEDIR.format(base_dir=skill.base_dir)}\n\n"
        f"<skill_files>\n{files_block}\n</skill_files>\n"
        f"</skill_content>"
    )
