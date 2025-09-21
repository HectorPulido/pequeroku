from __future__ import annotations

import asyncio
import os
import threading
import uuid

from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi.responses import JSONResponse, Response

import settings

from qemu_manager.models import (
    VMState,
    VMCreate,
    VMOut,
    VMAction,
    VMRecord,
    VMUploadFiles,
    ElementResponse,
    ListDirItem,
    VMPath,
    FileContent,
    VMSh,
)

from implementations import (
    RedisStore,
    Runner,
    send_files,
    list_dir,
    read_file,
    create_dir,
    download_file,
    download_folder,
)

from implementations.ssh_cache import cache_ssh_and_sftp
from security import verify_bearer_token


store = RedisStore(settings.REDIS_URL, settings.REDIS_PREFIX)
runner = Runner(store, settings.NODE_NAME)

vms_router = APIRouter(prefix="/vms", dependencies=[Depends(verify_bearer_token)])


# ---- Endpoints REST ----
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


@vms_router.post("/{vm_id}/list-dir", response_model=list[ListDirItem])
async def list_dir_endpoint(vm_id: str, root: VMPath) -> list[ListDirItem]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return list_dir(vm, root.path)


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


@vms_router.get("/{vm_id}/console/tail")
async def tail_console(vm_id: str, lines: int = 120) -> JSONResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e
    log = getattr(vm.proc, "console_log", None) if vm.proc else None
    out = ""
    if log and os.path.exists(log):
        try:
            # tail naive
            with open(log, "r", encoding="utf-8", errors="ignore") as f:
                data = f.readlines()
            out = "".join(data[-lines:])
        except Exception:
            out = ""
    return JSONResponse({"vm_id": vm_id, "lines": lines, "console": out})


@vms_router.post("/{vm_id}/execute-sh", response_model=ElementResponse)
async def execute_sh(vm_id: str, vm_command: VMSh) -> ElementResponse:
    print("Initiating bridge...")
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ElementResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ElementResponse(ok=False, reason="VM is not running")

    command = vm_command.command
    if not command.endswith(" /"):
        command += " /"

    output = ""
    try:
        val = cache_ssh_and_sftp(vm)
        cli = val["cli"]
        stdin, stdout, stderr = cli.exec_command(command)
        stdout.channel.settimeout(5)
        out: str = stdout.read().decode()
        err: str = stderr.read().decode()

        if len(out.strip()) > 0:
            output += f"Result: {out}\n"

        if len(err.strip()) > 0:
            output += f"Error: {err}\n"

        output.strip()

    except Exception as e:
        print("Error sending data", e)

    return ElementResponse(ok=True, reason=output)


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
