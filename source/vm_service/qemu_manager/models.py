import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Literal
import subprocess

from pydantic import BaseModel, Field


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
    proc: Optional[subprocess.Popen] = None
    console_log: Optional[str] = None
    pidfile: Optional[str] = None


# ===== Modelos API =====
class VMState(str, Enum):
    provisioning = "provisioning"
    running = "running"
    stopped = "stopped"
    error = "error"


class VMCreate(BaseModel):
    # pyrefly: ignore  # no-matching-overload
    vcpus: int = Field(ge=1, le=os.cpu_count() or 64, example=2)
    # pyrefly: ignore  # no-matching-overload
    mem_mib: int = Field(ge=256, example=2048)
    # pyrefly: ignore  # no-matching-overload
    disk_gib: int = Field(ge=5, example=10)
    base_image: Optional[str] = Field(None, description="VM_BASE_IMAGE Override")
    timeout_boot_s: Optional[int] = Field(
        None, description="VM_TIMEOUT_BOOT_S Override"
    )


class VMFile(BaseModel):
    path: str = Field("/", description="Path for the file")
    text: Optional[str] = Field(None, description="UTF-8 text content")
    content_b64: Optional[str] = Field(
        None, description="Base64-encoded bytes for binary files"
    )
    # pyrefly: ignore  # no-matching-overload
    mode: int = Field(example=0o644)


class VMPath(BaseModel):
    path: str = Field("/", description="Path for the file")


class VMUploadFiles(BaseModel):
    dest_path: Optional[str] = Field("/app", description="Base path for the files")
    files: list[VMFile] = Field(description="List of fields to send")
    clean: Optional[bool] = Field(False, description="Clean the dest path dir")


class VMAction(BaseModel):
    action: Literal["start", "stop", "reboot"]
    cleanup_disks: Optional[bool] = False


class VMSh(BaseModel):
    command: str


# ===== Dominio/Store =====
@dataclass
class VMRecord:
    id: str
    state: VMState
    workdir: str
    vcpus: int
    mem_mib: int
    disk_gib: int
    ssh_port: Optional[int] = None
    ssh_user: Optional[str] = None
    key_ref: Optional[str] = None
    error_reason: Optional[str] = None
    proc: Optional[VMProc] = None
    created_at: float = time.time()
    updated_at: float = time.time()
    booted_at: float = time.time()


class VMOut(BaseModel):
    id: str
    state: VMState
    node: str
    ssh_host: str
    ssh_port: Optional[int]
    ssh_user: Optional[str]
    key_ref: Optional[str]
    created_at: float
    updated_at: float
    booted_at: Optional[float]
    error_reason: Optional[str] = None

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


class ListDirItem(BaseModel):
    path: str
    name: str
    path_type: Literal["directory", "file"]


class ElementResponse(BaseModel):
    ok: bool
    reason: str = ""


class FileContent(BaseModel):
    name: str
    content: str
    length: int
    found: bool


class MachineMetrics(BaseModel):
    ts: float | int
    cpu_percent: float | int | None
    rss_bytes: int | None
    rss_human: str | None
    rss_mib: float | int | None
    num_threads: int | None
    io: dict | None
