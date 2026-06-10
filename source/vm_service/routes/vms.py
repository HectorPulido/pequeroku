from __future__ import annotations

import threading
import uuid
import shlex

from zipfile import error

from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi.responses import Response

from implementations.read_from_vm import list_dirs
import settings

from models import (
    VMState,
    VMCreate,
    VMEnsure,
    VMOut,
    VMAction,
    VMRecord,
    VMUploadFiles,
    ElementResponse,
    ListDirItem,
    VMPath,
    VMPaths,
    FileContent,
    VMSh,
    SearchHit,
    SearchRequest,
    VMShResponse,
    StartProcessRequest,
    ProcessStatusRequest,
    ProcessRef,
    StartProcessResponse,
    ProcessStatusResponse,
    ProcessActionResponse,
    ListeningPort,
    VMProxyRequest,
    VMProxyResponse,
)

from implementations import (
    RedisStore,
    Runner,
    send_files,
    read_file,
    create_dir,
    download_file,
    download_folder,
    start_process,
    process_status,
    stop_process,
    listening_ports,
    proxy_request,
)

from implementations.ssh_cache import exec_and_close, exec_and_close_status
from implementations.ssh_pool import borrow
from middleware import verify_bearer_token

store = RedisStore(settings.REDIS_URL, settings.REDIS_PREFIX)
runner = Runner(store, settings.NODE_NAME)

vms_router = APIRouter(prefix="/vms", dependencies=[Depends(verify_bearer_token)])


# ---- REST Endpoints ----
@vms_router.post("/", response_model=VMOut, status_code=201)
async def create_vm(req: VMCreate) -> VMOut:
    vm_id = str(uuid.uuid4())
    wd = runner.workdir(vm_id)
    vm = VMRecord(
        id=vm_id,
        state=VMState.provisioning,
        workdir=wd,
        vcpus=req.vcpus,
        mem_mib=req.mem_mib,
        disk_gib=req.disk_gib,
    )
    store.put(vm)
    runner.start(vm)
    return VMOut.from_record(vm, runner)


@vms_router.post("/{vm_id}/ensure", response_model=VMOut)
async def ensure_vm(vm_id: str, req: VMEnsure) -> VMOut:
    """
    Idempotently guarantee a VMRecord exists for ``vm_id``.

    vm-service keeps VM state in a Redis cache, while the orchestrator (Django)
    holds the durable source of truth. If the record is missing (e.g. Redis was
    restarted without persistence), rebuild it from the caller-provided specs in
    the ``stopped`` state so a follow-up ``start`` action can boot it. The qcow2
    overlay on disk is reused if present, so the VM comes back with its data.
    If the record already exists it is returned unchanged.
    """
    try:
        vm: "VMRecord" = store.get(vm_id)
        return VMOut.from_record(vm, runner)
    except KeyError:
        pass

    wd = runner.workdir(vm_id)
    vm = VMRecord(
        id=vm_id,
        state=VMState.stopped,
        workdir=wd,
        vcpus=req.vcpus,
        mem_mib=req.mem_mib,
        disk_gib=req.disk_gib,
    )
    store.put(vm)
    return VMOut.from_record(vm, runner)


@vms_router.get("/list/{vm_ids}", response_model=list[VMOut])
async def get_vms(vm_ids: str) -> list[VMOut]:
    vm_ids_keys = vm_ids.split(",")
    vm_records: list["VMOut"] = []
    for vm_id in vm_ids_keys:
        try:
            vm: "VMOut" = VMOut.from_record(store.get(vm_id), runner)
            vm_records.append(vm)
        except KeyError as e:
            print("Error with id: ", vm_id, e)
    return vm_records


@vms_router.get("/{vm_id}", response_model=VMOut)
async def get_vm(vm_id: str) -> VMOut:
    try:
        vm: "VMRecord" = store.get(vm_id)
        return VMOut.from_record(vm, runner)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e


@vms_router.get("/", response_model=list[VMOut])
async def list_vms() -> list[VMOut]:
    return [VMOut.from_record(v, runner) for v in store.all().values()]


@vms_router.post("/{vm_id}/actions", response_model=VMOut)
async def action_vm(vm_id: str, act: VMAction) -> VMOut:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    if act.action == "stop":
        runner.stop(vm, cleanup_disks=bool(act.cleanup_disks))
    elif act.action == "start":
        if vm.state == VMState.running:
            return VMOut.from_record(vm, runner)
        runner.start(vm)
        store.set_status(vm, VMState.provisioning)
    elif act.action == "reboot":
        runner.stop(vm)
        threading.Timer(1.0, lambda: runner.start(vm)).start()
        store.set_status(vm, VMState.provisioning)
    else:
        raise HTTPException(400, "Unsupported action")

    return VMOut.from_record(vm, runner)


@vms_router.post("/{vm_id}/upload-files", response_model=ElementResponse)
def upload_files(vm_id: str, files: VMUploadFiles) -> ElementResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return send_files(
        vm,
        files,
    )


@vms_router.post("/{vm_id}/list-dirs", response_model=list[ListDirItem])
def list_dirs_endpoint(vm_id: str, root: VMPaths) -> list[ListDirItem]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return list_dirs(vm, root.paths, root.depth)


@vms_router.post("/{vm_id}/read-file", response_model=FileContent)
def read_file_endpoint(vm_id: str, path: VMPath) -> FileContent:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return read_file(vm, path.path)


@vms_router.post("/{vm_id}/create-dir", response_model=ElementResponse)
def create_dir_endpoint(vm_id: str, path: VMPath) -> ElementResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return create_dir(vm, path.path)


@vms_router.delete("/{vm_id}", response_model=VMOut)
async def delete_vm(vm_id: str) -> VMOut:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e
    runner.stop(vm, cleanup_disks=True)
    return VMOut.from_record(vm, runner)


@vms_router.post("/{vm_id}/search", response_model=list[SearchHit])
def search_in_vm(vm_id: str, req: SearchRequest) -> list[SearchHit]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        raise HTTPException(status_code=400, detail="VM is not running")

    cmd_parts = [
        "grep",
        "-RInI",
    ]  # -R recursive, -I ignore binaries, -n show line numbers
    if req.case_insensitive:
        cmd_parts.append("-i")

    for d in req.exclude_dirs:
        cmd_parts.append(f"--exclude-dir={d}")

    for g in req.include_globs:
        if g.strip() == "*" or g.strip() == "":
            continue
        cmd_parts.append(f"--include={g}")

    cmd_parts.extend(["-e", req.pattern, req.root])
    command = " ".join(shlex.quote(p) for p in cmd_parts)

    try:
        with borrow(vm) as conn:
            # exec_and_close drains the output and CLOSES the channel (no leak).
            out_bytes, _ = exec_and_close(conn.cli, command, req.timeout_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Remote exec error: {e}")

    results: dict[str, list[str]] = {}
    total = 0

    for raw_line in out_bytes.splitlines():
        try:
            decoded = raw_line.decode("utf-8", errors="replace")
            parts = decoded.split(":", 2)
            if len(parts) < 3:
                continue
            file_path, line_num_txt, content_txt = parts[0], parts[1], parts[2]
            match_str = f"L{line_num_txt}: {content_txt}"
            results.setdefault(file_path, []).append(match_str)

            total += 1
            if req.max_results_total and total >= req.max_results_total:
                break
        except Exception:
            continue

    response: list[SearchHit] = [
        SearchHit(path=path, matchs=lines) for path, lines in results.items()
    ]

    return response


@vms_router.post("/{vm_id}/execute-sh", response_model=VMShResponse)
def execute_sh(vm_id: str, vm_command: VMSh) -> VMShResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return VMShResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return VMShResponse(ok=False, reason="VM is not running")

    import base64

    command = vm_command.command
    try:
        with borrow(vm) as conn:
            # exec_and_close_status applies the timeout to the channel and CLOSES
            # it (freeing the session slot instead of leaking toward MaxSessions)
            # and also captures the command's exit status for the API contract.
            out, err, code = exec_and_close_status(
                conn.cli, command, vm_command.timeout
            )

        try:
            return VMShResponse(
                ok=True, stdout=out.decode(), stderr=err.decode(), exit_code=code
            )
        except:
            out_b64 = base64.b64encode(out).decode("ascii")
            err_txt = err.decode("utf-8", errors="replace")
            return VMShResponse(ok=True, stdout=out_b64, stderr=err_txt, exit_code=code)

    except Exception as e:
        print("Error sending data", e)

    return VMShResponse(ok=False, reason="Something went wrong")


@vms_router.get("/{vm_id}/listening-ports", response_model=list[ListeningPort])
def listening_ports_ep(vm_id: str) -> list[ListeningPort]:
    """List the TCP ports an app is listening on inside the VM (preview autodetect)."""
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="VM doesn't exist") from e
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        raise HTTPException(status_code=400, detail="VM is not running")

    try:
        return listening_ports(vm)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Remote exec error: {e}") from e


@vms_router.post("/{vm_id}/proxy", response_model=VMProxyResponse)
def proxy_ep(vm_id: str, req: VMProxyRequest) -> VMProxyResponse:
    """Proxy one HTTP request to an app listening inside the VM (binary-safe)."""
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="VM doesn't exist") from e
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        raise HTTPException(status_code=400, detail="VM is not running")
    # SSRF guard: never tunnel to sshd; the channel dest is hard-pinned to the
    # guest's own 127.0.0.1, so it cannot pivot to other VMs or the node host.
    if req.target_port == 22 or not (1 <= req.target_port <= 65535):
        raise HTTPException(status_code=400, detail="Port not allowed")

    return proxy_request(vm, req)


@vms_router.post("/{vm_id}/start-process", response_model=StartProcessResponse)
def start_process_ep(vm_id: str, req: StartProcessRequest) -> StartProcessResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return StartProcessResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return StartProcessResponse(ok=False, reason="VM is not running")

    try:
        data = start_process(vm, req.command, req.cwd)
    except Exception as e:
        return StartProcessResponse(ok=False, reason=f"Process error: {e}")
    return StartProcessResponse(**data)


@vms_router.post("/{vm_id}/process-status", response_model=ProcessStatusResponse)
def process_status_ep(vm_id: str, req: ProcessStatusRequest) -> ProcessStatusResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ProcessStatusResponse(
            ok=False, job_id=req.job_id, reason="VM doesn't exist"
        )
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ProcessStatusResponse(
            ok=False, job_id=req.job_id, reason="VM is not running"
        )

    try:
        data = process_status(vm, req.job_id, req.lines, req.since_bytes, req.wait)
    except Exception as e:
        return ProcessStatusResponse(
            ok=False, job_id=req.job_id, reason=f"Process error: {e}"
        )
    return ProcessStatusResponse(**data)


@vms_router.post("/{vm_id}/stop-process", response_model=ProcessActionResponse)
def stop_process_ep(vm_id: str, req: ProcessRef) -> ProcessActionResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ProcessActionResponse(
            ok=False, job_id=req.job_id, reason="VM doesn't exist"
        )
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ProcessActionResponse(
            ok=False, job_id=req.job_id, reason="VM is not running"
        )

    try:
        data = stop_process(vm, req.job_id)
    except Exception as e:
        return ProcessActionResponse(
            ok=False, job_id=req.job_id, reason=f"Process error: {e}"
        )
    return ProcessActionResponse(**data)


@vms_router.get("/{vm_id}/download-file")
def download_file_ep(
    vm_id: str,
    path: str = Query(..., description="Absolute rute of the file"),
):
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ElementResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ElementResponse(ok=False, reason="VM is not running")

    data = download_file(vm, path)
    if not data:
        return ElementResponse(ok=False, reason="Issue with the file")

    return Response(**data)


@vms_router.get("/{vm_id}/download-folder")
def download_folder_ep(
    vm_id: str,
    root: str = Query("/app", description="Dict to download"),
    prefer_fmt: str = Query(
        "zip",
        pattern="^(zip|tar\\.gz)$",
        description="Prefeer format; zip, tar, *.gz",
    ),
):
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ElementResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ElementResponse(ok=False, reason="VM is not running")

    data = download_folder(vm, root, prefer_fmt)
    if not data:
        return ElementResponse(ok=False, reason="Issue with the file")

    return Response(**data)
