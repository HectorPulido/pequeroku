from __future__ import annotations

import threading
import uuid
import shlex

from typing import cast
from zipfile import error

import paramiko
from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi.responses import Response

from implementations.read_from_vm import list_dirs
import settings

from models import (
    VMState,
    VMCreate,
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
)

from implementations import (
    RedisStore,
    Runner,
    send_files,
    read_file,
    create_dir,
    download_file,
    download_folder,
)

from implementations.ssh_cache import cache_ssh_and_sftp
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
async def upload_files(vm_id: str, files: VMUploadFiles) -> ElementResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return send_files(
        vm,
        files,
    )


@vms_router.post("/{vm_id}/list-dirs", response_model=list[ListDirItem])
async def list_dirs_endpoint(vm_id: str, root: VMPaths) -> list[ListDirItem]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return list_dirs(vm, root.paths, root.depth)


@vms_router.post("/{vm_id}/read-file", response_model=FileContent)
async def read_file_endpoint(vm_id: str, path: VMPath) -> FileContent:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return read_file(vm, path.path)


@vms_router.post("/{vm_id}/create-dir", response_model=ElementResponse)
async def create_dir_endpoint(vm_id: str, path: VMPath) -> ElementResponse:
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
async def search_in_vm(vm_id: str, req: SearchRequest) -> list[SearchHit]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        raise HTTPException(status_code=400, detail="VM is not running")

    try:
        val = cache_ssh_and_sftp(vm)
        cli = cast(paramiko.SSHClient | None, val["cli"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SSH error: {e}")

    if not cli:
        raise HTTPException(status_code=500, detail="No cli available")

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
        _, stdout, _ = cli.exec_command(command)
        stdout.channel.settimeout(req.timeout_seconds)
        out_bytes = stdout.read()
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
async def execute_sh(vm_id: str, vm_command: VMSh) -> VMShResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return VMShResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return VMShResponse(ok=False, reason="VM is not running")

    import base64

    command = vm_command.command
    try:
        val = cache_ssh_and_sftp(vm)
        cli = cast(paramiko.SSHClient, val["cli"])

        if not cli:
            return VMShResponse(ok=False, reason="Not valid client")

        _, stdout, stderr = cli.exec_command(command)
        stdout.channel.settimeout(vm_command.timeout)

        out = stdout.read()
        err = stderr.read()

        try:
            return VMShResponse(ok=True, stdout=out.decode(), stderr=err.decode())
        except:
            out_b64 = base64.b64encode(out).decode("ascii")
            err_txt = err.decode("utf-8", errors="replace")
            return VMShResponse(ok=True, stdout=out_b64, stderr=err_txt)

    except Exception as e:
        print("Error sending data", e)

    return VMShResponse(ok=False, reason="Something went wrong")


@vms_router.get("/{vm_id}/download-file")
async def download_file_ep(
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
async def download_folder_ep(
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
