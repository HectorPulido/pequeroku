"""Container operations over ``vm_service``, with the v1 error contract.

Thin wrappers around ``VMServiceClient`` that translate node responses/exceptions
into the v1 envelope and apply output truncation. Shared by the containers
viewset AND the ephemeral runs lifecycle (phase B), so both behave identically.
"""

from __future__ import annotations

from dataclasses import asdict

import requests

from vm_manager import orchestration
from vm_manager.vm_client import VMAction, VMEnsure, VMFile, VMUploadFiles

from .errors import APIError

_ACTION_MAP = {"start": "start", "stop": "stop", "restart": "reboot"}


def _svc(container):
    return orchestration.get_service(container)


def _upstream(exc: Exception) -> APIError:
    if isinstance(exc, requests.Timeout):
        return APIError("timeout", "The node took too long to respond")
    return APIError("upstream_error", "The VM node returned an error")


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def exec_sh(container, command: str, timeout: int | None = None) -> dict:
    try:
        resp = _svc(container).execute_sh(
            str(container.container_id), command, timeout=timeout
        )
    except requests.RequestException as e:
        raise _upstream(e)

    if not resp.get("ok", False):
        reason = str(resp.get("reason", "")).lower()
        if "not running" in reason or "doesn't exist" in reason:
            raise APIError("machine_not_running", "Container is not running")
        raise APIError("upstream_error", resp.get("reason") or "Command failed")

    stdout, t1 = orchestration.truncate_output(_as_text(resp.get("stdout", "")))
    stderr, t2 = orchestration.truncate_output(_as_text(resp.get("stderr", "")))
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": resp.get("exit_code"),
        "truncated": t1 or t2,
    }


def start_process(container, command: str) -> dict:
    try:
        resp = _svc(container).start_process(str(container.container_id), command)
    except requests.RequestException as e:
        raise _upstream(e)
    if not resp.get("ok", False):
        raise APIError(
            "upstream_error", resp.get("reason") or "Could not start process"
        )
    return {"process_id": resp.get("job_id", ""), "pid": resp.get("pid")}


def process_status(container, process_id: str) -> dict:
    try:
        resp = _svc(container).process_status(
            str(container.container_id), job_id=process_id
        )
    except requests.RequestException as e:
        raise _upstream(e)
    if not resp.get("ok", False):
        raise APIError("not_found", resp.get("reason") or "Process not found")
    output, truncated = orchestration.truncate_output(_as_text(resp.get("log", "")))
    return {
        "process_id": process_id,
        "status": resp.get("status", "unknown"),
        "pid": resp.get("pid"),
        "output": output,
        "truncated": truncated,
    }


def stop_process(container, process_id: str) -> dict:
    try:
        resp = _svc(container).stop_process(str(container.container_id), process_id)
    except requests.RequestException as e:
        raise _upstream(e)
    return {"process_id": process_id, "stopped": bool(resp.get("ok", False))}


def upload_files(
    container, files: list[dict], dest_path: str = "/", clean: bool = False
) -> dict:
    payload_files = []
    for f in files:
        if f.get("content_b64") is not None:
            payload_files.append(VMFile(path=f["path"], content_b64=f["content_b64"]))
        else:
            payload_files.append(VMFile(path=f["path"], text=f.get("content") or ""))
    payload = VMUploadFiles(dest_path=dest_path, clean=clean, files=payload_files)
    try:
        _svc(container).upload_files_blob(str(container.container_id), asdict(payload))
    except requests.RequestException as e:
        raise _upstream(e)
    return {"written": len(payload_files)}


def read_file(container, path: str) -> dict:
    try:
        resp = _svc(container).read_file(str(container.container_id), path)
    except requests.RequestException as e:
        raise _upstream(e)
    content, truncated = orchestration.truncate_output(
        _as_text(resp.get("content", ""))
    )
    return {
        "path": path,
        "name": resp.get("name"),
        "found": bool(resp.get("found", False)),
        "length": resp.get("length", 0),
        "content": content,
        "truncated": truncated,
    }


def list_dir(container, path: str) -> list[dict]:
    try:
        return _svc(container).list_dirs(str(container.container_id), [path])
    except requests.RequestException as e:
        raise _upstream(e)


def listening_ports(container) -> list[dict]:
    try:
        return _svc(container).listening_ports(str(container.container_id))
    except Exception:
        # Degrade gracefully while the VM/app is still booting.
        return []


def ensure_record(container) -> None:
    """Rebuild the node's VM record from our specs if it lost it (idempotent)."""
    if not container.container_id:
        return
    try:
        _svc(container).ensure_vm(
            str(container.container_id),
            VMEnsure(
                vcpus=int(container.vcpus),
                mem_mib=int(container.memory_mb),
                disk_gib=int(container.disk_gib),
            ),
        )
    except Exception:
        pass


def action(container, action_name: str) -> None:
    vm_action = _ACTION_MAP[action_name]
    if action_name == "start":
        ensure_record(container)
    try:
        _svc(container).action_vm(
            str(container.container_id),
            VMAction(action=vm_action, cleanup_disks=False),
        )
    except requests.RequestException as e:
        raise _upstream(e)


def destroy(container) -> None:
    try:
        _svc(container).delete_vm(str(container.container_id))
    except Exception:
        # Best-effort: drop the row regardless; the reaper/reconciler cleans leaks.
        pass
    container.delete()
