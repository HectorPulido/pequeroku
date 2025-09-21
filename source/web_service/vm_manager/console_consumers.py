import asyncio
import contextlib
import json
from typing import Optional, Dict, Tuple

import websockets
from django.db import DatabaseError
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from pequeroku.mixins import ContainerAccessMixin, AuditMixin


class ConsoleConsumer(
    AsyncJsonWebsocketConsumer,
    ContainerAccessMixin,
    AuditMixin,
):
    """
    Client <-> Django <-> FastAPI
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.user = None

        # Multi-console state
        self.upstreams: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.reader_tasks: Dict[str, asyncio.Task] = {}
        self.active_sid: Optional[str] = None  # default focus (usually "s1")

    # Connection lifecycle
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        self.loop = asyncio.get_running_loop()

        try:
            allowed = await self._user_owns_container(self.pk, self.user.pk)
            if not allowed:
                await self.audit_ws(
                    action="ws.connect",
                    user=self.user,
                    target_type="container",
                    target_id=str(self.pk),
                    message="Unauthorized WebSocket connect attempt",
                    success=False,
                )
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        await self.accept()

        upstream_url, headers = await self._build_upstream_url_and_headers(self.pk)
        if not upstream_url:
            await self.audit_ws(
                action="ws.connect",
                user=self.user,
                target_type="container",
                target_id=str(self.pk),
                message="WebSocket connect failed: container not found",
                success=True,
            )
            await self.close(code=4404)
            return

        # Start with a single console "s1"
        try:
            ws = await self._open_upstream("s1", upstream_url, headers)
            self.upstreams["s1"] = ws
            await self._start_reader("s1")
            self.active_sid = "s1"
        except Exception as e:
            await self.send(
                text_data=f"Proxy error: could not connect initial console (s1) ({e})"
            )
            await self.close()
            return

        await self.send_json(
            {
                "type": "info",
                "message": "Connected",
                "sessions": list(self.upstreams.keys()),
                "active": self.active_sid,
            },
            close=False,
        )

    async def disconnect(self, code):
        # Cancel readers
        with contextlib.suppress(Exception):
            for t in self.reader_tasks.values():
                t.cancel()
            for t in self.reader_tasks.values():
                with contextlib.suppress(asyncio.CancelledError):
                    await t

        # Close upstream sockets
        with contextlib.suppress(Exception):
            for ws in self.upstreams.values():
                with contextlib.suppress(Exception):
                    await ws.close()

    # Message routing
    async def receive(self, text_data=None, bytes_data=None):
        if not self.upstreams:
            await self.send(text_data="Proxy: no active consoles")
            await self.close()
            return

        if text_data is not None:
            # Try to parse JSON; fall back to plain text -> active session
            payload = None
            try:
                payload = json.loads(text_data)
            except Exception:
                payload = None

            if isinstance(payload, dict):
                # Handle control messages first
                control = payload.get("control")
                if control in {"open", "close", "focus"}:
                    await self._handle_control(payload)
                    return

                # Command routing
                data = payload.get("data")
                if data is None:
                    await self.send_json(
                        {"type": "error", "message": "Missing 'data' for command."},
                        close=False,
                    )
                    return

                # Broadcast?
                if payload.get("broadcast") is True:
                    await self._audit("ws.cmd.broadcast", message=str(data))
                    await self._send_to_many(self.upstreams.keys(), str(data))
                    return

                # Target specific sid or active
                sid = payload.get("sid") or self.active_sid
                if not sid or sid not in self.upstreams:
                    await self.send_json(
                        {
                            "type": "error",
                            "message": f"Unknown or inactive sid '{sid}'.",
                        },
                        close=False,
                    )
                    return

                await self._audit("ws.cmd", target_sid=sid, message=str(data))
                await self._send_to_one(sid, str(data))
                return

            # Plain text: send to the active session
            if not self.active_sid or self.active_sid not in self.upstreams:
                await self.send_json(
                    {
                        "type": "error",
                        "message": "No active session to receive plain text.",
                    },
                    close=False,
                )
                return

            await self._audit("ws.cmd", target_sid=self.active_sid, message=text_data)
            await self._send_to_one(self.active_sid, text_data)
            return

        # Binary frames: send to active session by default
        elif bytes_data is not None:
            if not self.active_sid or self.active_sid not in self.upstreams:
                await self.send_json(
                    {
                        "type": "error",
                        "message": "No active session for binary payload.",
                    },
                    close=False,
                )
                return
            try:
                await self.upstreams[self.active_sid].send(bytes_data)
            except Exception as e:
                await self.send(
                    text_data=f"Proxy error when sending bin upstream[{self.active_sid}]: {e}"
                )
                await self._maybe_close_if_empty(self.active_sid)

    # Control handlers
    async def _handle_control(self, payload: dict):
        """
        Process control messages: open/close/focus a session.
        """
        action = payload.get("control")
        sid = payload.get("sid")

        if action == "open":
            if not sid or not isinstance(sid, str):
                await self.send_json(
                    {
                        "type": "error",
                        "message": "control=open requires a string 'sid'.",
                    },
                    close=False,
                )
                return
            if sid in self.upstreams:
                await self.send_json(
                    {"type": "error", "message": f"Session '{sid}' already exists."},
                    close=False,
                )
                return

            upstream_url, headers = await self._build_upstream_url_and_headers(self.pk)
            if not upstream_url:
                await self.send_json(
                    {
                        "type": "error",
                        "message": "Container not found for opening new session.",
                    },
                    close=False,
                )
                return

            try:
                ws = await self._open_upstream(sid, upstream_url, headers)
                self.upstreams[sid] = ws
                await self._start_reader(sid)
                # Optionally focus the new session
                self.active_sid = sid
                await self.send_json(
                    {
                        "type": "info",
                        "message": "session-opened",
                        "sid": sid,
                        "active": self.active_sid,
                    },
                    close=False,
                )
            except Exception as e:
                await self.send_json(
                    {
                        "type": "error",
                        "message": f"Failed to open session '{sid}': {e}",
                    },
                    close=False,
                )
            return

        if action == "close":
            if not sid or sid not in self.upstreams:
                await self.send_json(
                    {"type": "error", "message": f"Unknown sid '{sid}' to close."},
                    close=False,
                )
                return
            await self._close_session(sid)
            await self.send_json(
                {"type": "info", "message": "session-closed", "sid": sid}, close=False
            )
            await self._maybe_shutdown_if_no_sessions()
            return

        if action == "focus":
            if not sid or sid not in self.upstreams:
                await self.send_json(
                    {"type": "error", "message": f"Unknown sid '{sid}' to focus."},
                    close=False,
                )
                return
            self.active_sid = sid
            await self.send_json(
                {"type": "info", "message": "session-focused", "sid": sid}, close=False
            )
            return

        await self.send_json(
            {"type": "error", "message": f"Unknown control '{action}'."}, close=False
        )

    # Upstream management
    async def _build_upstream_url_and_headers(
        self, pk: int
    ) -> Tuple[str, Dict[str, str]]:
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

    async def _open_upstream(
        self, sid: str, upstream_url: str, headers: Dict[str, str]
    ) -> websockets.WebSocketClientProtocol:
        ws = await websockets.connect(
            upstream_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            additional_headers=headers,
        )
        # Small bootstrap for a pleasant shell UX
        await asyncio.sleep(0.2)
        await ws.send("cd /app && clear && ls -la\n")
        return ws

    async def _start_reader(self, sid: str) -> None:
        task = asyncio.create_task(self._pump_upstream_to_client(sid))
        self.reader_tasks[sid] = task

    async def _close_session(self, sid: str):
        # Cancel reader
        with contextlib.suppress(Exception):
            t = self.reader_tasks.pop(sid, None)
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        # Close socket
        with contextlib.suppress(Exception):
            ws = self.upstreams.pop(sid, None)
            if ws:
                await ws.close()
        # Adjust focus if needed
        if self.active_sid == sid:
            self.active_sid = next(iter(self.upstreams.keys()), None)

    async def _maybe_shutdown_if_no_sessions(self):
        if not self.upstreams:
            with contextlib.suppress(Exception):
                await self.close()

    async def _maybe_close_if_empty(self, sid: str):
        # Remove a broken session and close WS if none left
        await self._close_session(sid)
        await self._maybe_shutdown_if_no_sessions()  # Sending helpers

    async def _send_to_one(self, sid: str, data: str):
        # Ensure newline for interactive shells
        if not data.endswith("\n"):
            data = data + "\n"
        try:
            await self.upstreams[sid].send(data)
        except Exception as e:
            await self.send(text_data=f"Proxy error when sending upstream[{sid}]: {e}")
            await self._maybe_close_if_empty(sid)

    async def _send_to_many(self, sids, data: str):
        if not data.endswith("\n"):
            data = data + "\n"
        try:
            await asyncio.gather(*(self.upstreams[sid].send(data) for sid in sids))
        except Exception as e:
            await self.send(text_data=f"Proxy error when broadcasting upstream: {e}")

    async def _audit(self, action: str, message: str, target_sid: Optional[str] = None):
        await self.audit_ws(
            action=action,
            user=self.user,
            target_type="container",
            target_id=f"{self.pk}:{target_sid or self.active_sid or 'unknown'}",
            message=message,
            success=True,
        )

    # Reader loop per session
    async def _pump_upstream_to_client(self, sid: str):
        ws = self.upstreams[sid]
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    # Send a small envelope so the client knows which session the following bytes belong to
                    await self.send_json(
                        {"type": "stream-bytes", "sid": sid, "note": "binary follows"},
                        close=False,
                    )
                    await self.send(bytes_data=msg)
                else:
                    await self.send_json(
                        {"type": "stream", "sid": sid, "payload": msg}, close=False
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # Inform client but keep other sessions alive
            with contextlib.suppress(Exception):
                await self.send_json(
                    {
                        "type": "info",
                        "sid": sid,
                        "message": f"Proxy: upstream connection ended ({e})",
                    },
                    close=False,
                )
        finally:
            # Remove only this session; keep WS open if others remain
            await self._maybe_close_if_empty(sid)
