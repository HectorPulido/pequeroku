from __future__ import annotations
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
import subprocess

from pydantic import BaseModel, Field


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from implementations import Runner


@dataclass
class VMProc:
    """
    Lightweight handle to a running (or reattached) QEMU VM.
    Mirrors the original structure to avoid breaking external code.
    """

    workdir: str
    overlay: str
    seed_iso: str
    port_ssh: int
    proc: subprocess.Popen[Any] | None = None
    console_log: str | None = None
    pidfile: str | None = None


class VMState(str, Enum):
    provisioning = "provisioning"
    running = "running"
    stopped = "stopped"
    error = "error"


class VMCreate(BaseModel):
    vcpus: int = Field(
        default=..., ge=1, le=os.cpu_count() or 64, json_schema_extra={"example": 2}
    )
    mem_mib: int = Field(default=..., ge=256, json_schema_extra={"example": 2})
    disk_gib: int = Field(default=..., ge=5, json_schema_extra={"example": 10})
    base_image: str | None = Field(None, description="VM_BASE_IMAGE Override")
    timeout_boot_s: int | None = Field(None, description="VM_TIMEOUT_BOOT_S Override")


class VMAction(BaseModel):
    action: Literal["start", "stop", "reboot"]
    cleanup_disks: bool | None = False


@dataclass
class VMRecord:
    id: str
    state: VMState
    workdir: str
    vcpus: int
    mem_mib: int
    disk_gib: int
    ssh_port: int | None = None
    ssh_user: str | None = None
    key_ref: str | None = None
    error_reason: str | None = None
    proc: VMProc | None = None
    created_at: float = time.time()
    updated_at: float = time.time()
    booted_at: float = time.time()


class VMOut(BaseModel):
    id: str
    state: VMState
    node: str
    ssh_host: str
    ssh_port: int | None
    ssh_user: str | None
    key_ref: str | None
    created_at: float
    updated_at: float
    booted_at: float | None
    error_reason: str | None = None

    @staticmethod
    # pyrefly: ignore  # unknown-name
    def from_record(vm: "VMRecord", runner: "Runner") -> "VMOut":
        return VMOut(
            id=vm.id,
            state=vm.state,
            node=runner.node_name,
            ssh_host="127.0.0.1",
            ssh_port=vm.ssh_port,
            ssh_user=vm.ssh_user,
            key_ref=None,
            created_at=vm.created_at,
            updated_at=vm.updated_at,
            error_reason=vm.error_reason,
            booted_at=vm.booted_at,
        )
