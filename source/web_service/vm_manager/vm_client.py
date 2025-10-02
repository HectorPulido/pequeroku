from __future__ import annotations

import requests
from django.utils import timezone
from dataclasses import dataclass, asdict, field
from typing import Literal, cast

from .models import Node


VMState = Literal["provisioning", "running", "stopped", "error"]
VMActionType = Literal["start", "stop", "reboot"]
PathType = Literal["directory", "file"]


@dataclass
class SearchRequest:
    pattern: str
    root: str
    case_insensitive: bool = False
    include_globs: list[str] = field(default_factory=list)
    exclude_dirs: list[str] = field(
        default_factory=lambda: [".git"],
    )
    max_results_total: int | None = None
    timeout_seconds: int = 10

    def apply_exclude_diff(self):
        exclude_dirs = [
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "target",
            "build",
            "dist",
            "__pycache__",
            "Library",
            ".gradle",
            "Pods",
            ".m2",
            "DerivedData",
        ] + self.exclude_dirs
        exclude_dirs = list(set([item for item in exclude_dirs if item.strip()]))

        self.exclude_dirs = exclude_dirs
        return self


@dataclass
class VMCreate:
    """Payload for create the vm."""

    vcpus: int
    mem_mib: int
    disk_gib: int
    base_image: str | None = None
    timeout_boot_s: int | None = None


@dataclass
class VMAction:
    """Payload of actions on the vm."""

    action: VMActionType
    cleanup_disks: bool | None = False


@dataclass
class VMPath:
    """Route inside the VM"""

    path: str = "/"


@dataclass
class VMPaths:
    """Routes inside the VM"""

    paths: list[str] | None = None
    depth: int = 1


@dataclass
class VMFile:
    """
    File to upload
    """

    mode: int = 0o644
    path: str = "/"
    text: str | None = ""
    content_b64: str | None = ""


@dataclass
class VMUploadFiles:
    """Payload to upload multiple files"""

    files: list[VMFile]
    dest_path: str | None = "/app"
    clean: bool | None = False


class VMServiceClient:
    """
    Client for the vm-service API
    """

    def __init__(
        self,
        node: Node,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        extra_headers: dict[str, str] | None = None,
        blocking: bool = False,
    ) -> None:
        self.blocking: bool = blocking
        self.node: Node = node
        self.base_url: str = cast(str, node.node_host).rstrip("/")
        self.timeout: float = timeout
        self.session: requests.Session = session or requests.Session()
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        auth_token: str | None = cast(str | None, node.auth_token)
        if auth_token and len(auth_token) > 0:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        if extra_headers:
            self.headers.update(extra_headers)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle(self, resp: requests.Response) -> object:
        detail: object | str | None = None
        if not resp.ok:
            self.set_healthy(False)
            try:
                detail = cast(object, resp.json())
            except Exception:
                detail = resp.text
            raise requests.HTTPError(
                f"HTTP {resp.status_code} - {resp.reason} - {detail}", response=resp
            )
        status: int = resp.status_code
        if status == 204 or not resp.content:
            self.set_healthy(True)
            return None

        self.set_healthy(True)
        return cast(object, resp.json())

    def set_healthy(self, healthy: bool):
        if not self.blocking:
            return

        if healthy:
            self.node.healthy = True
            self.node.heartbeat_at = timezone.now()
            self.node.save()
            return
        # if not healthy
        try:
            health = self.get_health()
            health_data: dict[str, str] = cast(dict[str, str], health.json())
            if health.ok:
                self.node.healthy = health_data["ok"] == "True"
                self.node.heartbeat_at = timezone.now()
            else:
                self.node.healthy = False
        except:
            self.node.healthy = False
        finally:
            self.node.save()

    def get_health(self) -> requests.Response:
        """GET /health"""
        resp = self.session.get(
            self._url("/health"), headers=self.headers, timeout=self.timeout
        )
        return resp

    def list_vms(self) -> list[dict[str, object]]:
        """GET /vms — Lista todas las VMs."""
        resp = self.session.get(
            self._url("/vms"), headers=self.headers, timeout=self.timeout
        )
        return cast(list[dict[str, object]], self._handle(resp))

    def create_vm(self, payload: VMCreate) -> dict[str, object]:
        """POST /vms — Create a VM."""
        data = {k: v for k, v in asdict(payload).items() if v is not None}
        resp = self.session.post(
            self._url("/vms"), json=data, headers=self.headers, timeout=self.timeout
        )
        return cast(dict[str, object], self._handle(resp))

    def get_vms(self, vm_ids: list[str]) -> dict[str, object]:
        """GET /vms/list/{vm_ids}"""
        query = ",".join(vm_ids)
        resp = self.session.get(
            self._url(f"/vms/list/{query}"), headers=self.headers, timeout=self.timeout
        )
        return cast(dict[str, object], self._handle(resp))

    def get_vm(self, vm_id: str) -> dict[str, object]:
        """GET /vms/{vm_id} — Obtiene una VM por id."""
        resp = self.session.get(
            self._url(f"/vms/{vm_id}"), headers=self.headers, timeout=self.timeout
        )
        return cast(dict[str, object], self._handle(resp))

    def delete_vm(self, vm_id: str) -> dict[str, object]:
        """DELETE /vms/{vm_id} — Elimina (o apaga y borra) una VM."""
        resp = self.session.delete(
            self._url(f"/vms/{vm_id}"), headers=self.headers, timeout=self.timeout
        )
        return cast(dict[str, object], self._handle(resp))

    def action_vm(self, vm_id: str, action: VMAction) -> dict[str, object]:
        """POST /vms/{vm_id}/actions — Ejecuta acción (start/stop/reboot)."""
        data = {k: v for k, v in asdict(action).items() if v is not None}
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/actions"),
            json=data,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def upload_files(self, vm_id: str, payload: VMUploadFiles) -> dict[str, object]:
        """POST /vms/{vm_id}/upload-files — Sube archivos de texto a la VM."""
        data = asdict(payload)
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/upload-files"),
            json=data,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def upload_files_blob(self, vm_id: str, payload: dict) -> dict[str, object]:
        """POST /vms/{vm_id}/upload-files — Sube archivos de texto a la VM."""
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/upload-files"),
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def list_dirs(
        self, vm_id: str, paths: VMPaths | list[str]
    ) -> list[dict[str, object]]:
        """POST /vms/{vm_id}/list-dirs"""
        p = {"paths": paths, "depth": 1} if isinstance(paths, list) else asdict(paths)
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/list-dirs"),
            json=p,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(list[dict[str, object]], self._handle(resp))

    def read_file(self, vm_id: str, path: VMPath | str) -> dict[str, object]:
        """POST /vms/{vm_id}/read-file — Lee un archivo y devuelve su contenido."""
        p = {"path": path} if isinstance(path, str) else asdict(path)
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/read-file"),
            json=p,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def create_dir(self, vm_id: str, path: VMPath | str) -> dict[str, object]:
        """POST /vms/{vm_id}/create-dir — Crea un directorio."""
        p = {"path": path} if isinstance(path, str) else asdict(path)
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/create-dir"),
            json=p,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def tail_console(self, vm_id: str, lines: int = 120) -> object:
        """GET /vms/{vm_id}/console/tail — Obtiene el tail de la consola."""
        params = {"lines": lines}
        resp = self.session.get(
            self._url(f"/vms/{vm_id}/console/tail"),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        return self._handle(resp)

    def statistics(self, vm_id: str) -> object:
        """GET /metrics/{vm_id}"""
        resp = self.session.get(
            self._url(f"/metrics/{vm_id}"),
            headers=self.headers,
            timeout=self.timeout,
        )
        return self._handle(resp)

    def execute_sh(self, vm_id: str, vm_command: str) -> dict[str, object]:
        """POST /vms/{vm_id}/execute-sh"""
        p = {"command": vm_command}
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/execute-sh"),
            json=p,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))

    def download_file(self, vm_id: str, path: str):
        """POST /vms/{vm_id}/download-file"""
        return self.session.get(
            self._url(f"/vms/{vm_id}/download-file"),
            params={"path": path},
            headers=self.headers,
            timeout=self.timeout,
        )

    def download_folder(self, vm_id: str, root: str = "/app", prefer_fmt: str = "zip"):
        """POST /vms/{vm_id}/download-folder"""
        return self.session.get(
            self._url(f"/vms/{vm_id}/download-folder"),
            params={"root": root, "prefer_fmt": prefer_fmt},
            headers=self.headers,
            timeout=None,
        )

    def search(self, vm_id: str, payload: SearchRequest) -> dict[str, object]:
        """POST /vms/{vm_id}/search — Search for files."""
        data = asdict(payload)
        resp = self.session.post(
            self._url(f"/vms/{vm_id}/search"),
            json=data,
            headers=self.headers,
            timeout=self.timeout,
        )
        return cast(dict[str, object], self._handle(resp))
