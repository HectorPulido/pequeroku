"""HTTP client for the PequeRoku public API (/api/v1).

All MCP tools go through this — no privileged side paths, full dogfooding of the
public contract. Errors from the API's stable envelope are raised as
:class:`PlatformError` so the server layer can turn them into actionable text.
"""

from __future__ import annotations

from typing import Any

import httpx


class PlatformError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class PlatformClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._root = base_url.rstrip("/")
        self.base = self._root + "/api/v1"
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    # --- plumbing --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._client.request(method, f"{self.base}{path}", **kwargs)
        except httpx.TimeoutException:
            raise PlatformError("timeout", "The platform API timed out")
        except httpx.HTTPError as e:
            raise PlatformError("network_error", f"Could not reach the platform: {e}")

        if resp.status_code >= 400:
            raise self._to_error(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    @staticmethod
    def _to_error(resp: httpx.Response) -> PlatformError:
        try:
            err = resp.json().get("error", {})
            return PlatformError(
                err.get("code", "http_error"),
                err.get("message", f"HTTP {resp.status_code}"),
            )
        except Exception:
            return PlatformError("http_error", f"HTTP {resp.status_code}")

    # --- runs ------------------------------------------------------------

    def run_code(
        self, command: str, files=None, type=None, timeout_seconds=120
    ) -> dict:
        payload: dict[str, Any] = {
            "command": command,
            "timeout_seconds": timeout_seconds,
        }
        if files:
            payload["files"] = files
        if type:
            payload["type"] = type
        return self._request("POST", "/runs/", json=payload)

    # --- types -----------------------------------------------------------

    def list_types(self) -> list[dict]:
        """Flavors the key owner may use: id, name, specs and credit cost."""
        data = self._request("GET", "/types/")
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data or []

    # --- containers ------------------------------------------------------

    def list_containers(self) -> list[dict]:
        data = self._request("GET", "/containers/")
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data or []

    def get_container_by_name(self, name: str) -> dict | None:
        for c in self.list_containers():
            if c.get("name") == name:
                return c
        return None

    def create_container(self, type: str, name: str | None = None) -> dict:
        payload: dict[str, Any] = {"type": type}
        if name:
            payload["name"] = name
        return self._request("POST", "/containers/", json=payload)

    def get_or_create_container(self, name: str, type: str | None = None) -> dict:
        existing = self.get_container_by_name(name)
        if existing:
            return existing
        if not type:
            raise PlatformError(
                "invalid_request",
                f"No container named '{name}'; pass a type to create one.",
            )
        return self.create_container(type=type, name=name)

    def container_exec(
        self, container_id, command, background=False, timeout=None
    ) -> dict:
        payload: dict[str, Any] = {"command": command, "background": background}
        if timeout:
            payload["timeout"] = timeout
        return self._request("POST", f"/containers/{container_id}/exec/", json=payload)

    def process_status(self, container_id, process_id) -> dict:
        return self._request(
            "GET", f"/containers/{container_id}/processes/{process_id}/"
        )

    def write_files(self, container_id, files, dest_path="/") -> dict:
        return self._request(
            "PUT",
            f"/containers/{container_id}/files/",
            json={"files": files, "dest_path": dest_path},
        )

    def read_path(self, container_id, path) -> dict:
        f = self._request(
            "GET", f"/containers/{container_id}/files/", params={"path": path}
        )
        if f and f.get("found"):
            return {"kind": "file", **f}
        entries = self._request(
            "GET", f"/containers/{container_id}/dirs/", params={"path": path}
        )
        return {"kind": "dir", "path": path, "entries": entries or []}

    def get_preview(self, container_id) -> list[dict]:
        ports = self._request("GET", f"/containers/{container_id}/ports/") or []
        for p in ports:
            rel = p.get("preview_path") or (
                f"/api/containers/{container_id}/preview/{p.get('port')}/"
            )
            # Absolute, ready to fetch (with your API key) or embed in a browser.
            p["preview_url"] = f"{self._root}{rel}"
        return ports

    def fetch_preview(self, container_id, port, path="/") -> dict:
        """GET the live app response served inside the VM, authenticated by the key.

        The preview endpoint accepts our ``Authorization: Bearer`` header (already
        set on the client), so an agent can read what the app actually serves
        without a browser session. Redirects are followed inside the preview.
        """
        rel = path if path.startswith("/") else "/" + path
        url = f"{self._root}/api/containers/{container_id}/preview/{port}{rel}"
        try:
            resp = self._client.request("GET", url, follow_redirects=True)
        except httpx.TimeoutException:
            raise PlatformError("timeout", "The preview request timed out")
        except httpx.HTTPError as e:
            raise PlatformError("network_error", f"Could not reach the preview: {e}")
        ctype = resp.headers.get("content-type", "")
        lowered = ctype.lower()
        is_text = (
            lowered.startswith("text/")
            or "json" in lowered
            or "xml" in lowered
            or "javascript" in lowered
        )
        body = resp.text if is_text else f"<{len(resp.content)} bytes of {ctype or 'binary'}>"
        return {
            "status": resp.status_code,
            "content_type": ctype,
            "url": url,
            "body": body,
        }

    def destroy_container(self, container_id) -> None:
        self._request("DELETE", f"/containers/{container_id}/")
