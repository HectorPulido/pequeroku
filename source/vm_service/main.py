from __future__ import annotations

import os
import base64
import re
import uvicorn
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
import settings
from models import (
    VMState,
    VMRecord,
)
from implementations import (
    RedisStore,
    TTYBridge,
    Runner,
)

from routes import router_metrics, vms_router


store = RedisStore(settings.REDIS_URL, settings.REDIS_PREFIX)
runner = Runner(store, settings.NODE_NAME)

# ===== FastAPI app =====
app = FastAPI(title="vm-service", version="0.1.0")


@app.get("/health")
async def health():
    return JSONResponse({"ok": "True"})


@app.websocket("/vms/{vm_id}/tty")
async def tty_ws(websocket: WebSocket, vm_id: str):
    def _try_to_resize():
        if not raw.startswith(b"__RESIZE__"):
            return False
        try:
            s = raw.decode("ascii", errors="ignore")
            # Extract first two integers in order (cols, rows)
            nums = [int(n) for n in re.findall(r"\d+", s)]
            if len(nums) >= 2:
                chan = getattr(bridge, "chan", None)
                if chan is not None:
                    try:
                        chan.resize_pty(width=int(nums[0]), height=int(nums[1]))
                    except Exception:
                        return False
            return True
        except Exception:
            # Ignore parse errors, fallback to sending raw
            return False

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
        vm=vm,
    )
    bridge.start()

    try:
        while True:
            data = await websocket.receive_text()
            # Try base64 path (frontend -> django -> vm-service uses base64 text frames)
            try:
                raw = base64.b64decode(data, validate=True)
                # Control message: __RESIZE__ <cols>x<rows> (flexible separators)
                if _try_to_resize():
                    continue
                await bridge.send(raw)
            except Exception:
                # Not valid base64; fall through as plain text
                pass
            # Fallback: treat as plain text (do not force newline)
            await bridge.send(data)
    except WebSocketDisconnect:
        bridge.close()
    except Exception:
        bridge.close()
        try:
            await websocket.close()
        except Exception:
            pass


app.include_router(router_metrics)
app.include_router(vms_router)

# ===== Entrypoint =====
if __name__ == "__main__":
    os.makedirs(os.path.join(settings.VM_BASE_DIR, "vms"), exist_ok=True)
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
