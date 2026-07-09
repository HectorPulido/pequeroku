"""Long-term memory tools over the VM: full CRUD (save/read/edit/delete).

Durable, cross-conversation facts the agent chooses to remember (decisions,
conventions, environment quirks, user preferences) — as opposed to the per-turn
plan handled by ``todowrite`` or the conversation history handled by
``conversations.py``.

Storage: a single JSON object keyed by id, at ``/app/.pequenin/memory.json``:

    {"<id>": {"content": "...", "created_at": "...", "updated_at": "..."}, ...}

``save_memory`` and ``edit_memory`` both UPSERT (create or update a memory by id) —
agents are unreliable about whether a memory already exists, so neither errors on a
missing/existing id; they just write it. ``delete_memory`` removes one by id.
Matching is by exact id (an id is auto-derived from the content when you save
without one). It reaches the VM through the same ``VMServiceClient`` bridge as the
file tools (``vm.get_client`` + read_file / upload_files), so it is testable with
the same fake client. The file lives in the user's workspace, so it is
human-editable from the IDE (hence ``indent=2``).
"""

from __future__ import annotations

import datetime
import json
import re

from vm_manager.vm_client import VMFile, VMUploadFiles

from .base import Tool, ToolContext, truncate
from . import vm

# Relative to the workdir (/app); resolved per turn so it honors config.workdir.
_MEMORY_REL = ".pequenin/memory.json"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 48) -> str:
    """Stable, filesystem/key-safe id derived from free text."""
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "memory"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _read_memory(client, cid: str, path: str) -> dict:
    """Load the memory object, tolerating a missing file or corrupt JSON."""
    resp = client.read_file(cid, path)
    if not isinstance(resp, dict) or not resp.get("found"):
        return {}
    try:
        data = json.loads(resp.get("content") or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_memory(client, cid: str, path: str, data: dict) -> None:
    client.upload_files(
        cid,
        VMUploadFiles(
            dest_path="/",
            clean=False,
            files=[
                VMFile(path=path, text=json.dumps(data, ensure_ascii=False, indent=2))
            ],
        ),
    )


def _upsert(data: dict, mem_id: str, content: str) -> bool:
    """Write/replace ``mem_id``'s content, preserving created_at. Returns True if
    it updated an existing memory, False if it created a new one."""
    existing = data.get(mem_id)
    existed = isinstance(existing, dict)
    created = existing.get("created_at") if existed else None
    entry = {"content": content, "created_at": created or _now_iso()}
    if existed:
        entry["updated_at"] = _now_iso()
    data[mem_id] = entry
    return existed


class SaveMemoryTool(Tool):
    name = "save_memory"
    description = (
        "Create or update a durable memory (upsert), stored in the VM at "
        "/app/.pequenin/memory.json, so future turns and conversations can recall "
        "it. Save concise, self-contained facts worth remembering — decisions, "
        "conventions, environment quirks, user preferences — NOT transient task "
        "state (use todowrite for that). Omit `id` to auto-derive one from the "
        "content; pass an existing `id` to update that memory in place."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact to remember: one concise, self-contained statement.",
            },
            "id": {
                "type": "string",
                "description": (
                    "Optional slug identifying this memory. Pass an existing id to "
                    "update it; omit to auto-generate one from the content."
                ),
            },
        },
        "required": ["content"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        content = (args.get("content") or "").strip()
        if not content:
            return "Error: `content` is required (the fact to remember)."

        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, _MEMORY_REL)
        data = _read_memory(client, cid, path)

        raw_id = (args.get("id") or "").strip()
        if raw_id:
            mem_id = _slugify(raw_id)
            updated = _upsert(data, mem_id, content)
        else:
            # Derive an id from the content; dedupe identical content, otherwise keep
            # distinct facts that slugify the same from colliding.
            base = _slugify(content)
            mem_id, i = base, 2
            while mem_id in data:
                entry = data[mem_id]
                if isinstance(entry, dict) and entry.get("content") == content:
                    return f"Memory '{mem_id}' already saved (no change)."
                mem_id = f"{base}-{i}"
                i += 1
            data[mem_id] = {"content": content, "created_at": _now_iso()}
            updated = False

        _write_memory(client, cid, path, data)
        vm.audit(
            "save_memory",
            cid,
            "Memory updated" if updated else "Memory saved",
            {"id": mem_id},
        )
        verb = "Updated" if updated else "Saved"
        return f"{verb} memory '{mem_id}'. Total memories: {len(data)}."


class ReadMemoryTool(Tool):
    name = "read_memories"
    read_only = True
    description = (
        "Recall the durable facts saved earlier with save_memory (from the VM's "
        "/app/.pequenin/memory.json). Read them when starting a non-trivial task to "
        "reuse what you already know about this project and user. Returns every "
        "saved memory with its id."
    )
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, _MEMORY_REL)
        data = _read_memory(client, cid, path)

        items = [(k, v) for k, v in data.items() if isinstance(v, dict)]
        if not items:
            return "(no memories saved yet)"

        items.sort(key=lambda kv: kv[1].get("created_at") or "")
        vm.audit("read_memories", cid, "Memories read", {"count": len(items)})

        lines = [f"Saved memories ({len(items)}):"]
        for mem_id, entry in items:
            created = (entry.get("created_at") or "")[:10]  # YYYY-MM-DD
            when = f" ({created})" if created else ""
            lines.append(f"- [{mem_id}]{when}: {(entry.get('content') or '').strip()}")
        return truncate("\n".join(lines))


class EditMemoryTool(Tool):
    name = "edit_memory"
    description = (
        "Update a memory's content by its id (from read_memories). This is an "
        "upsert: if the id does not exist yet, the memory is created. Preserves the "
        "original created_at and stamps updated_at when it updates an existing one."
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Id of the memory to update (created if new).",
            },
            "content": {
                "type": "string",
                "description": "The new content; replaces the memory's current content.",
            },
        },
        "required": ["id", "content"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        mem_id = _slugify((args.get("id") or "").strip())
        content = (args.get("content") or "").strip()
        if not content:
            return "Error: `content` is required (the new memory text)."

        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, _MEMORY_REL)
        data = _read_memory(client, cid, path)

        updated = _upsert(data, mem_id, content)
        _write_memory(client, cid, path, data)
        vm.audit(
            "edit_memory",
            cid,
            "Memory updated" if updated else "Memory created",
            {"id": mem_id},
        )
        return f"{'Updated' if updated else 'Created'} memory '{mem_id}'."


class DeleteMemoryTool(Tool):
    name = "delete_memory"
    description = (
        "Delete a memory by its id (from read_memories) when it is wrong or no "
        "longer true. Errors if no memory has that id."
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Id of the memory to delete."},
        },
        "required": ["id"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        mem_id = _slugify((args.get("id") or "").strip())

        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, _MEMORY_REL)
        data = _read_memory(client, cid, path)

        if mem_id not in data:
            if not data:
                return f"Error: no memory '{mem_id}' (no memories saved yet)."
            return f"Error: no memory with id '{mem_id}'. Saved ids: {', '.join(sorted(data)[:10])}."

        data.pop(mem_id)
        _write_memory(client, cid, path, data)
        vm.audit("delete_memory", cid, "Memory deleted", {"id": mem_id})
        return f"Deleted memory '{mem_id}'. Total memories: {len(data)}."
