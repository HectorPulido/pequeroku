"""PequeRoku API client.

Wraps the stable ``/api/v1`` contract. Errors from the API envelope surface as
:class:`PequeRokuError` with the enumerated ``code``. Output truncation and
credit/quota semantics are handled server-side; this is a transport with
ergonomics, not logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


class PequeRokuError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class RunResult:
    id: str
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    truncated: bool = False
    duration_ms: int | None = None
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "succeeded" and (self.exit_code in (0, None))

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(
            id=str(d.get("id", "")),
            status=d.get("status", ""),
            stdout=d.get("stdout", ""),
            stderr=d.get("stderr", ""),
            exit_code=d.get("exit_code"),
            truncated=bool(d.get("truncated", False)),
            duration_ms=d.get("duration_ms"),
            error_code=d.get("error_code", ""),
        )


class PequeRoku:
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost",
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    # --- plumbing --------------------------------------------------------

    def _req(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise PequeRokuError("timeout", "The platform API timed out")
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
                raise PequeRokuError(
                    err.get("code", "http_error"),
                    err.get("message", f"HTTP {resp.status_code}"),
                )
            except PequeRokuError:
                raise
            except Exception:
                raise PequeRokuError("http_error", f"HTTP {resp.status_code}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PequeRoku":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- types -----------------------------------------------------------

    def types(self) -> list[dict]:
        return self._req("GET", "/types/")

    # --- containers ------------------------------------------------------

    def list_containers(self) -> list[dict]:
        data = self._req("GET", "/containers/")
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data or []

    def create_container(
        self, type: str | int, name: str | None = None, ttl_seconds: int | None = None
    ) -> dict:
        payload: dict[str, Any] = {"type": type}
        if name:
            payload["name"] = name
        if ttl_seconds:
            payload["ttl_seconds"] = ttl_seconds
        return self._req("POST", "/containers/", json=payload)

    def get_container(self, container_id: int) -> dict:
        return self._req("GET", f"/containers/{container_id}/")

    def destroy_container(self, container_id: int) -> None:
        self._req("DELETE", f"/containers/{container_id}/")

    def action(self, container_id: int, action: str) -> dict:
        return self._req(
            "POST", f"/containers/{container_id}/actions/", json={"action": action}
        )

    def exec(
        self,
        container_id: int,
        command: str,
        timeout: int | None = None,
        background: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {"command": command, "background": background}
        if timeout:
            payload["timeout"] = timeout
        return self._req("POST", f"/containers/{container_id}/exec/", json=payload)

    def process_status(self, container_id: int, process_id: str) -> dict:
        return self._req("GET", f"/containers/{container_id}/processes/{process_id}/")

    def write_files(
        self, container_id: int, files: list[dict], dest_path: str = "/"
    ) -> dict:
        return self._req(
            "PUT",
            f"/containers/{container_id}/files/",
            json={"files": files, "dest_path": dest_path},
        )

    def read_file(self, container_id: int, path: str) -> dict:
        return self._req(
            "GET", f"/containers/{container_id}/files/", params={"path": path}
        )

    def list_dir(self, container_id: int, path: str = "/app") -> list[dict]:
        return self._req(
            "GET", f"/containers/{container_id}/dirs/", params={"path": path}
        )

    def ports(self, container_id: int) -> list[dict]:
        return self._req("GET", f"/containers/{container_id}/ports/")

    # --- runs ------------------------------------------------------------

    def run(
        self,
        command: str,
        files: list[dict] | None = None,
        type: str | int | None = None,
        timeout_seconds: int = 120,
        wait: bool = True,
        poll_interval: float = 2.0,
    ) -> RunResult:
        """One-shot: run a command in a throwaway VM and return the result.

        ``wait=False`` submits an async run and returns immediately with the
        pending result (poll with :meth:`get_run`). ``wait=True`` (default) runs
        synchronously, except for long timeouts where it submits async and polls.
        """
        payload: dict[str, Any] = {
            "command": command,
            "timeout_seconds": timeout_seconds,
        }
        if files:
            payload["files"] = files
        if type is not None:
            payload["type"] = type

        if not wait:
            payload["async"] = True
            return RunResult.from_dict(self._req("POST", "/runs/", json=payload))

        data = self._req("POST", "/runs/", json=payload)
        return RunResult.from_dict(data)

    def get_run(self, run_id: str) -> RunResult:
        return RunResult.from_dict(self._req("GET", f"/runs/{run_id}/"))

    def wait_run(
        self, run_id: str, poll_interval: float = 2.0, max_wait: float = 600.0
    ) -> RunResult:
        """Poll an async run until it finishes (or ``max_wait`` elapses)."""
        deadline = time.monotonic() + max_wait
        while True:
            result = self.get_run(run_id)
            if result.status not in ("pending", "running"):
                return result
            if time.monotonic() >= deadline:
                return result
            time.sleep(poll_interval)
