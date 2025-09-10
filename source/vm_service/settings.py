import os
from pathlib import Path
from pwd import getpwnam
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
VM_BASE_DIR = os.path.join(BASE_DIR, "vm_data")

VM_SSH_USER = os.environ.get("VM_SSH_USER", "root")
VM_SSH_PRIVKEY = os.environ.get(
    "VM_SSH_PRIVKEY", os.path.expanduser("~/.ssh/id_vm_pequeroku")
)
# "/Users/hectorpulido/.ssh/id_ed25519"
VM_QEMU_BIN = os.environ.get("VM_QEMU_BIN", "/usr/bin/qemu-system-x86_64")
VM_BASE_IMAGE = os.environ.get(
    "VM_BASE_IMAGE", os.path.join(VM_BASE_DIR, "base", "jammy-golden.qcow2")
)
VM_TIMEOUT_BOOT_S = int(os.environ.get("VM_TIMEOUT_BOOT_S", "600"))
NODE_NAME = os.environ.get("NODE_NAME", "local-node")

REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/1")
REDIS_PREFIX: str = os.environ.get("REDIS_PREFIX", "vmservice:")

AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "")

VM_RUN_AS_UID = getpwnam("vmnet").pw_uid
VM_RUN_AS_GID = getpwnam("vmnet").pw_gid
