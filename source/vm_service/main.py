from __future__ import annotations

import os
import threading
import uuid
import asyncio

import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    APIRouter,
)
from fastapi.responses import JSONResponse


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
    TTYBridge,
    Runner,
    generate_console,
    send_files,
    list_dir,
    read_file,
    create_dir,
)

from security import verify_bearer_token


store = RedisStore(settings.REDIS_URL, settings.REDIS_PREFIX)
runner = Runner(store, settings.NODE_NAME)

# ===== FastAPI app =====
app = FastAPI(title="vm-service", version="0.1.0")

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


# ---- Endpoints REST ----
@router.post("/vms", response_model=VMOut, status_code=201)
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


@router.get("/vms/list/{vm_ids}", response_model=list[VMOut])
async def get_vms(vm_ids: str) -> list[VMOut]:
    vm_ids_keys = vm_ids.split(",")
    vm_records: list["VMRecord"] = []
    for vm_ids in vm_ids_keys:
        vm: "VMOut" = VMOut.from_record(store.get(vm_ids), runner)
        vm_records.append(vm)
    return vm_records


@router.get("/vms/{vm_id}", response_model=VMOut)
async def get_vm(vm_id: str) -> VMOut:
    try:
        vm: "VMRecord" = store.get(vm_id)
        return VMOut.from_record(vm, runner)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e


@router.get("/vms", response_model=list[VMOut])
async def list_vms() -> list[VMOut]:
    return [VMOut.from_record(v, runner) for v in store.all().values()]


@router.post("/vms/{vm_id}/actions", response_model=VMOut)
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
    elif act.action == "reboot":
        runner.stop(vm)
        threading.Timer(1.0, lambda: runner.start(vm)).start()
    else:
        raise HTTPException(400, "Unsupported action")

    return VMOut.from_record(vm, runner)


@router.post("/vms/{vm_id}/upload-files", response_model=ElementResponse)
async def upload_files(vm_id: str, files: VMUploadFiles) -> ElementResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return send_files(
        vm,
        files,
    )


@router.post("/vms/{vm_id}/list-dir", response_model=list[ListDirItem])
async def list_dir_endpoint(vm_id: str, root: VMPath) -> list[ListDirItem]:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return list_dir(vm, root.path)


@router.post("/vms/{vm_id}/read-file", response_model=FileContent)
async def read_file_endpoint(vm_id: str, path: VMPath) -> FileContent:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return read_file(vm, path.path)


@router.post("/vms/{vm_id}/create-dir", response_model=ElementResponse)
async def create_dir_endpoint(vm_id: str, path: VMPath) -> ElementResponse:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e

    return create_dir(vm, path.path)


@router.delete("/vms/{vm_id}", response_model=VMOut)
async def delete_vm(vm_id: str) -> VMOut:
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError as e:
        raise HTTPException(404, "VM not found") from e
    # detener y limpiar
    runner.stop(vm, cleanup_disks=True)
    return VMOut.from_record(vm, runner)


@router.get("/vms/{vm_id}/console/tail")
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


@router.post("/vms/{vm_id}/execute-sh", response_model=ElementResponse)
async def execute_sh(vm_id: str, vm_command: VMSh) -> ElementResponse:
    print("Initiating bridge...")
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        return ElementResponse(ok=False, reason="VM doesn't exist")
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        return ElementResponse(ok=False, reason="VM is not running")

    command = vm_command.command
    if not command.endswith("\n"):
        command += "\n"

    try:
        cli, chan = generate_console(
            settings.VM_SSH_PRIVKEY,
            "127.0.0.1",
            vm.ssh_port,
            vm.ssh_user,
        )
        await asyncio.sleep(1)
        chan.send(command)
        await asyncio.sleep(1)
    except Exception as e:
        print("Error sending data", e)

    try:
        chan.close()
        cli.close()
    except Exception as e:
        print("Error closing...", e)

    return ElementResponse(ok=True, reason="")


@app.websocket("/vms/{vm_id}/tty")
async def tty_ws(websocket: WebSocket, vm_id: str):
    print("Initiating ws...")
    await websocket.accept()
    try:
        vm: "VMRecord" = store.get(vm_id)
    except KeyError:
        await websocket.send_text("VM not found")
        await websocket.close()
        return
    if vm.state != VMState.running or not vm.ssh_port or not vm.ssh_user:
        await websocket.send_text("VM not running")
        await websocket.close()
        return

    bridge = TTYBridge(
        websocket,
        host="127.0.0.1",
        port=vm.ssh_port,
        user=vm.ssh_user,
        key_path=settings.VM_SSH_PRIVKEY,
    )
    bridge.start()

    try:
        while True:
            data = await websocket.receive_text()
            if not data.endswith("\n"):
                data += "\n"
            await bridge.send(data)
    except WebSocketDisconnect:
        bridge.close()
    except Exception:
        bridge.close()
        try:
            await websocket.close()
        except Exception:
            pass


app.include_router(router)

# ===== Entrypoint =====
if __name__ == "__main__":
    os.makedirs(os.path.join(settings.VM_BASE_DIR, "vms"), exist_ok=True)
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
