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
