import os
import time
import psutil
from fastapi import HTTPException, APIRouter, Depends
from security import verify_bearer_token
from implementations import RedisStore, Runner
import settings

from models import MachineMetrics


router_metrics = APIRouter(
    prefix="/metrics", dependencies=[Depends(verify_bearer_token)]
)
store = RedisStore(settings.REDIS_URL, settings.REDIS_PREFIX)
runner = Runner(store, settings.NODE_NAME)


def human_bytes(n: float | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return "-"


def safe(call, default=None):
    try:
        return call()
    except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
        return default


@router_metrics.get("/{vm_id}", response_model=MachineMetrics)
async def get_vms(vm_id: str) -> MachineMetrics:
    vm_base_dir = settings.VM_BASE_DIR or ""
    base = os.path.join(vm_base_dir, "vms", vm_id, "qemu.pid")
    print(f"Base path for PID {vm_id} is {base}")

    pid = None
    try:
        with open(base, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception:
        pid = None

    if not pid:
        raise HTTPException(404, "PID File not found, is machine running?")

    try:
        p = psutil.Process(pid)
        p.cpu_percent(interval=None)
    except Exception as e:
        print("Error with PID", e)
        raise HTTPException(500, "Error with PID, something went wrong")

    out: MachineMetrics | None = None
    try:
        rss = safe(lambda: p.memory_info().rss)
        out = MachineMetrics(
            ts=time.time(),
            cpu_percent=safe(lambda: p.cpu_percent(interval=None)),
            rss_bytes=rss,
            rss_human=human_bytes(rss),
            rss_mib=rss / (1024 * 1024) if rss else None,
            num_threads=safe(p.num_threads),
            io=safe(lambda: p.io_counters()._asdict()) or {},
        )

    except psutil.Error as e:
        print("Error with psutils", e)
        raise HTTPException(500, f"Issues with psutils {e}")

    return out
