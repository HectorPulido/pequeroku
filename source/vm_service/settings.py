import json
import os
import platform
from pathlib import Path
from pwd import getpwnam
from dotenv import load_dotenv

_ = load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
VM_BASE_DIR = os.path.join(BASE_DIR, "vm_data")

VM_SSH_USER = os.environ.get("VM_SSH_USER", "root")
VM_SSH_PRIVKEY = os.environ.get(
    "VM_SSH_PRIVKEY", os.path.expanduser("~/.ssh/id_vm_pequeroku")
)

# QEMU binary. An explicit VM_QEMU_BIN wins, but ONLY if it actually exists —
# otherwise fall back to the binary for this host's arch. This self-heals a config
# that pins the wrong arch (e.g. a template's arm64 path baked onto an x86 host).
_qemu_default = (
    "/usr/bin/qemu-system-aarch64"
    if platform.machine() in ("aarch64", "arm64")
    else "/usr/bin/qemu-system-x86_64"
)
_qemu_env = os.environ.get("VM_QEMU_BIN", "").strip()
VM_QEMU_BIN = _qemu_env if (_qemu_env and os.path.exists(_qemu_env)) else _qemu_default
if _qemu_env and _qemu_env != VM_QEMU_BIN:
    print(
        f"[vm_service] VM_QEMU_BIN={_qemu_env} not found; using {VM_QEMU_BIN} "
        f"for arch {platform.machine()}"
    )
VM_BASE_IMAGE = os.environ.get(
    "VM_BASE_IMAGE", os.path.join(VM_BASE_DIR, "base", "debian12-golden.qcow2")
)
VM_TIMEOUT_BOOT_S = int(os.environ.get("VM_TIMEOUT_BOOT_S", "600"))
NODE_NAME = os.environ.get("NODE_NAME", "local-node")

# CPU affinity for QEMU on the KVM path, in `taskset -c` syntax (e.g. "0-3" or
# "0,2,4"). Empty disables pinning and lets the kernel scheduler place threads.
VM_TASKSET_CPUS: str = os.environ.get("VM_TASKSET_CPUS", "")

# Whether to build and attach a cloud-init seed ISO at boot. Off when VM_BASE_IMAGE
# is a pre-baked golden image (user + SSH key + sshd config already inside) so VMs
# skip the ~40s cloud-init pipeline and SSH is ready as soon as sshd starts.
def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_use_cloud_init(base_image: str) -> "tuple[bool, str]":
    """Resolve whether to attach a cloud-init seed ISO at boot.

    Resolution order (first match wins):
      1. Explicit VM_USE_CLOUD_INIT env var -> honored exactly (explicit always
         wins; prod sets `true`).
      2. <base_image>.meta.json -> its "golden" flag (true -> off, false -> on).
         Everything we create writes this sidecar: build-golden.sh -> golden:true,
         ensure-base-image.sh (auto-download) -> golden:false.
      3. No metadata, but the base image file exists -> off. A bare image with no
         sidecar is assumed to be a pre-baked golden (the historical convention;
         the only meta-less images are goldens built before metadata existed).
      4. No image yet -> on (safe default; a clean machine will cloud-init).
    """
    raw = os.environ.get("VM_USE_CLOUD_INIT")
    if raw is not None:
        return _truthy(raw), "env override"

    meta_path = f"{base_image}.meta.json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        golden = meta.get("golden")
        if golden is True:
            return False, f"golden metadata ({meta_path})"
        if golden is False:
            return True, f"cloud-image metadata ({meta_path})"
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as e:
        print(f"[vm_service] Ignoring unreadable {meta_path}: {e}")

    if os.path.exists(base_image):
        return False, "existing image, no metadata (assumed golden)"
    return True, "default"


VM_USE_CLOUD_INIT, _cloud_init_source = _resolve_use_cloud_init(VM_BASE_IMAGE)
print(
    f"[vm_service] cloud-init={'on' if VM_USE_CLOUD_INIT else 'off'} "
    f"(source={_cloud_init_source}, base_image={VM_BASE_IMAGE})"
)

REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/1")
REDIS_PREFIX: str = os.environ.get("REDIS_PREFIX", "vmservice:")

AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "")

vm_run_as_uid = None
vm_run_as_gid = None
try:
    vm_run_as_uid = getpwnam("vmnet").pw_uid
    vm_run_as_gid = getpwnam("vmnet").pw_gid
except Exception as e:
    print("Could not load vmnet", e)

VM_RUN_AS_UID = vm_run_as_uid
VM_RUN_AS_GID = vm_run_as_gid
