"""Conversation storage for the AI assistant — lives INSIDE the user's VM.

Each conversation is a JSON file under ``/app/.pequenin/`` named
``ai_memory_<id>.json`` (``{"messages": [...]}``) — the VM holds the content. The
pointer to the *active* conversation is NOT in the VM: it lives in the DB
(``AIMemory.current_conversation`` per user+container) so it is durable across a
VM reset/rebuild and known without hitting the VM. This module is the one place
that talks to both, shared by the WebSocket consumer (async, via
``sync_to_async``) and the REST endpoint (sync).

Everything here is best-effort and synchronous: callers run it off the event loop
(the consumer wraps it in ``sync_to_async``; DRF runs sync views in a threadpool).

NOTE: a workspace "reset" wipes everything under ``/app`` except
readme.txt/config.json, so conversations are cleared on reset / VM rebuild.
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, cast

from vm_manager.models import Container
from vm_manager.vm_client import VMServiceClient, VMUploadFiles, VMFile, VMPaths
from internal_config.models import AIMemory

MEMORY_DIR = "/app/.pequenin"
_NAME_RE = re.compile(r"^ai_memory_(\d+)\.json$")


def memory_path(conversation_id: int) -> str:
    return f"{MEMORY_DIR}/ai_memory_{int(conversation_id)}.json"


def _service(container: Container) -> VMServiceClient:
    return VMServiceClient(cast(Any, container.node))


def read_json(container: Container, path: str) -> dict | None:
    try:
        resp = _service(container).read_file(cast(str, container.container_id), path)
        if isinstance(resp, dict) and resp.get("found"):
            return cast(dict, json.loads(cast(str, resp.get("content")) or "{}"))
    except Exception as exc:  # VM unreachable / not ready / bad JSON
        print(f"[conversations] read {path} failed: {exc}")
    return None


def write_json(container: Container, path: str, data: dict) -> None:
    try:
        _service(container).upload_files(
            cast(str, container.container_id),
            VMUploadFiles(
                dest_path="/",
                clean=False,
                files=[VMFile(path=path, text=json.dumps(data, ensure_ascii=False))],
            ),
        )
    except Exception as exc:
        print(f"[conversations] write {path} failed: {exc}")


def list_conversation_ids(container: Container) -> list[int]:
    ids: list[int] = []
    try:
        entries = _service(container).list_dirs(
            cast(str, container.container_id),
            VMPaths(paths=[MEMORY_DIR], depth=1),
        )
        if isinstance(entries, list):
            for e in entries:
                name = e.get("name", "") if isinstance(e, dict) else ""
                m = _NAME_RE.match(name)
                if m:
                    ids.append(int(m.group(1)))
    except Exception as exc:
        print(f"[conversations] list failed: {exc}")
    return sorted(set(ids))


def read_conversation(container: Container, conversation_id: int) -> list[dict]:
    data = read_json(container, memory_path(conversation_id))
    msgs = (data or {}).get("messages")
    return cast(list[dict], msgs) if isinstance(msgs, list) else []


def write_conversation(
    container: Container, conversation_id: int, messages: list[dict]
) -> None:
    write_json(container, memory_path(conversation_id), {"messages": messages})


def get_current_id(user: Any, container: Container) -> int | None:
    """Active conversation pointer — stored in the DB (durable), not the VM."""
    try:
        row = AIMemory.objects.filter(user=user, container=container).first()
    except Exception as exc:
        print(f"[conversations] get_current_id failed: {exc}")
        return None
    if not row:
        return None
    n = int(row.current_conversation or 0)
    return n if n > 0 else None


def set_current_id(user: Any, container: Container, conversation_id: int) -> None:
    try:
        AIMemory.objects.update_or_create(
            user=user,
            container=container,
            defaults={"current_conversation": int(conversation_id)},
        )
    except Exception as exc:
        print(f"[conversations] set_current_id failed: {exc}")


def delete_conversation(container: Container, conversation_id: int) -> None:
    try:
        path = memory_path(conversation_id)
        _service(container).execute_sh(
            cast(str, container.container_id), f"rm -f {shlex.quote(path)}"
        )
    except Exception as exc:
        print(f"[conversations] delete {conversation_id} failed: {exc}")


def next_conversation_id(container: Container) -> int:
    ids = list_conversation_ids(container)
    return (max(ids) + 1) if ids else 1


def list_with_current(user: Any, container: Container) -> dict:
    """Convenience for the REST endpoint: ids (from the VM) + the active id (DB)."""
    ids = list_conversation_ids(container)
    current = get_current_id(user, container)
    if current is None or current not in ids:
        current = ids[0] if ids else 1
    if current not in ids:
        ids = sorted(set(ids + [current]))
    return {"conversations": ids, "current": current}
