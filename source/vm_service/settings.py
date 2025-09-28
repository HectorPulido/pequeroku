import os
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

VM_QEMU_BIN = os.environ.get("VM_QEMU_BIN", "/usr/bin/qemu-system-x86_64")
VM_BASE_IMAGE = os.environ.get(
    "VM_BASE_IMAGE", os.path.join(VM_BASE_DIR, "base", "jammy-golden.qcow2")
)
VM_TIMEOUT_BOOT_S = int(os.environ.get("VM_TIMEOUT_BOOT_S", "600"))
NODE_NAME = os.environ.get("NODE_NAME", "local-node")

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


# This will only work on x86
VM_USE_MICRO_VM: bool = os.environ.get("VM_USE_MICRO_VM", "").lower() == "true"
VM_KERNEL: str = os.environ.get("VM_KERNEL", "")
VM_INITRD: str = os.environ.get("VM_INITRD", "")
VM_KERNEL_APPEND: str = "console=ttyS0 root=/dev/vda rw"
