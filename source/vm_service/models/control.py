from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, Field


class VMSh(BaseModel):
    command: str
    timeout: int = 5


class VMShResponse(BaseModel):
    ok: bool
    reason: str = ""
    stdout: str | bytes = ""
    stderr: str | bytes = ""


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


class ListeningPort(BaseModel):
    port: int = Field(..., description="TCP port a process is listening on.")
    address: str = Field(
        ...,
        description="Bind address (0.0.0.0/::/* or 127.0.0.1). All are reachable "
        "from the preview proxy because the direct-tcpip channel originates inside the VM.",
    )
    process: str | None = Field(
        None, description="Process name owning the socket, if known."
    )
    pid: int | None = Field(None, description="Process id owning the socket, if known.")


class VMProxyRequest(BaseModel):
    target_port: int = Field(..., description="App port inside the VM to proxy to.")
    method: str = Field("GET", description="HTTP method.")
    path: str = Field(
        "/", description="Origin-form request target including query string."
    )
    headers: dict[str, str] = Field(
        default_factory=dict, description="Request headers to forward upstream."
    )
    body_b64: str | None = Field(None, description="Base64-encoded request body.")
    timeout: float = Field(30.0, description="Per-request timeout in seconds.")


class VMProxyResponse(BaseModel):
    ok: bool = True
    status: int = Field(502, description="Upstream HTTP status (or 502 on failure).")
    reason: str = ""
    headers: list[tuple[str, str]] = Field(
        default_factory=list, description="Upstream response headers."
    )
    body_b64: str = Field("", description="Base64-encoded response body.")


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


class StartProcessRequest(BaseModel):
    command: str = Field(..., description="Shell command to run detached in the VM.")
    cwd: str = Field("/app", description="Working directory for the process.")


class ProcessStatusRequest(BaseModel):
    job_id: str = Field(..., description="Job id returned by start-process.")
    lines: int = Field(80, description="Number of trailing log lines to return.")


class ProcessRef(BaseModel):
    job_id: str = Field(..., description="Job id returned by start-process.")


class StartProcessResponse(BaseModel):
    ok: bool
    job_id: str = ""
    pid: int | None = None
    log_path: str = ""
    reason: str = ""


class ProcessStatusResponse(BaseModel):
    ok: bool
    job_id: str
    status: Literal["running", "exited", "unknown"] = "unknown"
    pid: int | None = None
    log: str = ""
    reason: str = ""


class ProcessActionResponse(BaseModel):
    ok: bool
    job_id: str
    status: str = ""
    reason: str = ""
