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


class VMFile(BaseModel):
    path: str = Field("/", description="Path for the file")
    text: str | None = Field(None, description="UTF-8 text content")
    content_b64: str | None = Field(
        None, description="Base64-encoded bytes for binary files"
    )
    mode: int = Field(json_schema_extra={"example": 0o644})


class VMPath(BaseModel):
    path: str = Field("/", description="Paths for the files")


class VMPaths(BaseModel):
    paths: list[str] = Field(["/"], description="Paths for the files")
    depth: int = Field(1, description="Depth for the tree")


class VMUploadFiles(BaseModel):
    dest_path: str | None = Field("/app", description="Base path for the files")
    files: list[VMFile] = Field(..., description="List of fields to send")
    clean: bool | None = Field(False, description="Clean the dest path dir")


class VMAction(BaseModel):
    action: Literal["start", "stop", "reboot"]
    cleanup_disks: bool | None = False


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


class ListDirItem(BaseModel):
    path: str
    name: str
    path_type: Literal["directory", "file"]

    def __hash__(self):
        return hash((self.path,))


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
    io: dict[str, object] | None


class SearchRequest(BaseModel):
    pattern: str = Field(..., description="Text/regex pattern to search with grep.")
    root: str = Field("/app", description="Root directory where the search starts.")
    case_insensitive: bool = Field(False, description="Use -i flag in grep.")
    include_globs: list[str] = Field(
        default_factory=list, description="Patterns for --include=*.ext"
    )
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [".git"],
        description="Directories to exclude with --exclude-dir=",
    )
    max_results_total: int | None = Field(
        None, description="Hard cap for the total number of matches."
    )
    timeout_seconds: int = Field(
        10, description="Timeout for the SSH channel in seconds."
    )


class SearchHit(BaseModel):
    path: str
    matchs: list[str]
