from __future__ import annotations
import asyncio
import contextlib
import base64
from urllib.parse import parse_qs

from typing import Any, cast

import websockets
from websockets.asyncio.client import ClientConnection
from django.db import DatabaseError
from django.contrib.auth.models import User
from channels.generic.websocket import AsyncWebsocketConsumer

from pequeroku.mixins import ContainerAccessMixin, AuditMixin


class ConsoleConsumer(AsyncWebsocketConsumer, ContainerAccessMixin, AuditMixin):
    """
    One-session-per-WebSocket bridge:
    - Frontend <-> Django: raw bytes (binary frames) or plain text (keystrokes)
    - Django <-> vm-service (FastAPI): base64 text upstream, raw bytes downstream

    Multiple consoles are supported by opening multiple WS connections from the
    frontend, one per `sid` provided via query string (?sid=s1, ?sid=s2, ...).
    """

    FIRST_COMMAND: str = (
        "export TERM=xterm-256color && "
        "cd /app && "
        "clear && "
        "echo 'Welcome to your machine'\n"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.user: User | None = None
        self.sid: str = "s1"

        # Upstream vm-service websocket
        self._upstream: ClientConnection | None = None
        self._pump_task: asyncio.Task[Any] | None = None

    # Connection lifecycle
    async def connect(self):
        self.user = cast(User | None, self.scope.get("user", None))
        if not self.user or getattr(self.user, "is_anonymous", True):
            await self.close(code=4401)
            return

        try:
            self.pk = cast(
                int, self.scope.get("url_route", {}).get("kwargs", {}).get("pk", -1)
            )
        except Exception:
            await self.close(code=4400)
            return

        # Extract sid from query string (?sid=s1). Default "s1".
        try:
            raw_qs = self.scope.get("query_string") or b""
            qs = parse_qs(raw_qs.decode("utf-8", errors="ignore"))
            sid = (qs.get("sid") or ["s1"])[0]
            if sid.strip():
                self.sid = sid.strip()
        except Exception:
            self.sid = "s1"

        try:
            allowed = await self._user_owns_container(self.pk, cast(int, self.user.pk))
            if not allowed:
                await self.audit_ws(
                    action="ws.connect",
                    user=self.user,
                    target_type="container",
                    target_id=str(self.pk),
                    message=f"Unauthorized WS attempt (sid={self.sid})",
                    success=False,
                )
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return
        # defer accept until upstream is ready

        upstream_url, headers = await self._build_upstream_url_and_headers(self.pk)
        if not upstream_url:
            await self.audit_ws(
                action="ws.connect",
                user=self.user,
                target_type="container",
                target_id=str(self.pk),
                message=f"Container not found (sid={self.sid})",
                success=False,
            )
            await self.close(code=4404)
            return

        upstream_ok = await self._open_upstream(upstream_url, headers)
        if not upstream_ok:
            await self.close(code=4404)
            return

        await self.accept()

        await self.audit_ws(
            action="ws.connect",
            user=self.user,
            target_type="container",
            target_id=f"{self.pk}:{self.sid}",
            message=f"Connected (sid={self.sid})",
            success=True,
        )

        # Start upstream -> frontend pump
        self._pump_task = asyncio.create_task(self._pump_upstream_to_client())

        # Optional: small UX banner (harmless for raw terminals)
        try:
            await self.send(text_data=f"[connected sid={self.sid}]")
        except Exception:
            pass

    async def _open_upstream(self, upstream_url: str, headers: dict[str, str]):
        try:
            self._upstream = await websockets.connect(
                upstream_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                additional_headers=headers,
                max_size=None,
            )

            if not self._upstream:
                return None

            await asyncio.sleep(1)
            data_bytes = self.FIRST_COMMAND.encode("utf-8", errors="ignore")
            enc = base64.b64encode(data_bytes).decode("ascii")
            await self._upstream.send(enc)

            return True
        except Exception as e:
            print("[ConsoleConsumer] _open_upstream error", e)
            return False

    async def disconnect(self, code):
        # Stop pump
        with contextlib.suppress(Exception):
            if self._pump_task:
                _ = self._pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._pump_task
        # Close upstream
        with contextlib.suppress(Exception):
            if self._upstream:
                await self._upstream.close()
        self._upstream = None

    # Message routing: Frontend -> Upstream (base64 text)
    async def receive(
        self, text_data: str | None = None, bytes_data: bytes | None = None
    ):
        if not self._upstream:
            await self.send(text_data="[proxy] no upstream")
            await self.close()
            return

        try:
            if bytes_data is not None:
                # Binary from frontend -> base64 text upstream
                if isinstance(bytes_data, (bytearray, memoryview)):
                    bytes_data = bytes(bytes_data)
                enc = base64.b64encode(bytes_data).decode("ascii")
                await self._upstream.send(enc)
                return

            if text_data is not None:
                # Treat incoming text as keystrokes -> base64 text upstream (utf-8)
                data_bytes = text_data.encode("utf-8", errors="ignore")
                enc = base64.b64encode(data_bytes).decode("ascii")
                await self._upstream.send(enc)
                return
        except Exception as e:
            await self.send(text_data=f"[proxy] send error: {e}")
            await self._graceful_close()
            return

    # Upstream -> Frontend pump: raw bytes down to client
    async def _pump_upstream_to_client(self):
        assert self._upstream is not None
        ws = self._upstream
        try:
            async for msg in ws:
                # vm-service sends base64-encoded text frames for TTY data.
                # Decode to raw bytes for the frontend. If decoding fails, forward as text.
                if isinstance(msg, (bytes, bytearray)):
                    # Fallback: if upstream ever sends binary, pass through.
                    await self.send(bytes_data=msg)
                else:
                    try:
                        raw = base64.b64decode(msg, validate=True)
                        await self.send(bytes_data=raw)
                    except Exception:
                        await self.send(text_data=str(msg))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            with contextlib.suppress(Exception):
                await self.send(text_data=f"[proxy] upstream ended: {e}")
        finally:
            await self._graceful_close()

    async def _graceful_close(self):
        with contextlib.suppress(Exception):
            if self._upstream:
                await self._upstream.close()
        self._upstream = None
        with contextlib.suppress(Exception):
            await self.close()

    # Helpers
    async def _build_upstream_url_and_headers(
        self, pk: int
    ) -> tuple[str, dict[str, str]]:
        """
        Build vm-service tty URL and auth headers.
        """
        container_obj, node = await self._get_container_with_node(pk)
        if not container_obj or not node:
            return "", {}
        container_node_host: str = node.node_host
        container_node_host = container_node_host.replace("http://", "ws://")
        container_node_host = container_node_host.replace("https://", "wss://")
        container_id = container_obj.container_id
        upstream_url = f"{container_node_host}vms/{container_id}/tty"
        custom_headers = {"Authorization": f"Bearer {node.auth_token}"}
        return upstream_url, custom_headers
