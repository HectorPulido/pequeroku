from __future__ import annotations

import asyncio
import json
from asyncio.events import AbstractEventLoop
from typing import Optional

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.apps import apps
from django.db import DatabaseError

from .usecases.vm_management import QemuSession
from .usecases.audit import audit_log_ws

CTRL_C = "\x03"
CTRL_D = "\x04"


class ConsoleConsumer(AsyncJsonWebsocketConsumer):
    """
    Interactive shell over WebSocket for a container-backed VM.

    Key refactors:
    - Preserves original protocol/contract (actions: cmd, ctrlc, ctrld, clear, restart).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.loop: Optional[AbstractEventLoop] = None
        self.session: Optional[QemuSession] = None

    # -------------------------
    # Lifecycle
    # -------------------------
    async def connect(self):
        # Authentication gate
        if self.scope["user"].is_anonymous:
            await self.close(code=4401)
            return

        # Route params
        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        self.loop = asyncio.get_running_loop()

        # Authorization: user must own the container
        try:
            allowed = await self._user_owns_container(self.pk, self.scope["user"].pk)
            if not allowed:
                await audit_log_ws(
                    action="ws.connect",
                    user=self.scope["user"],
                    ip=self.ws_client_ip(self.scope),
                    user_agent=self.ws_user_agent(self.scope),
                    target_type="container",
                    target_id=self.pk,
                    message="Unauthorized WebSocket connect attempt",
                    success=False,
                )
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        await self.accept()
        await self._send_json({"type": "info", "message": "Connected"})

        # Create a fresh QemuSession bound to this socket (no global cache)
        container_obj = await self._get_container(self.pk)
        if not container_obj:
            await audit_log_ws(
                action="ws.connect",
                user=self.scope["user"],
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="WebSocket connect failed: container not found",
                success=False,
            )
            await self.close(code=4404)
            return

        # Build the session in a thread; pass async-safe callbacks
        try:
            self.session = await sync_to_async(
                lambda: QemuSession(
                    container_obj,
                    on_line=self._on_line,
                    on_close=self._on_close,
                )
            )()
        except Exception as e:
            await self._send_json(
                {"type": "error", "message": "Unable to open shell session"}
            )
            await audit_log_ws(
                action="ws.connect",
                user=self.scope["user"],
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Failed to open shell session",
                metadata={"error": str(e)},
                success=False,
            )
            await self.close(code=1011)
            return

        # Auto prime shell
        await self._ensure_alive()
        await self._send_to_session("cd /app")
        await self._send_to_session("ls -la")

        await audit_log_ws(
            action="ws.connect",
            user=self.scope["user"],
            ip=self.ws_client_ip(self.scope),
            user_agent=self.ws_user_agent(self.scope),
            target_type="container",
            target_id=self.pk,
            message="WebSocket session established",
            success=True,
        )

    async def disconnect(self, code):
        """
        Detach callbacks to avoid calling back into a dead consumer.
        We do not keep or reuse the session across connections.
        """
        if self.session:
            try:
                self.session.set_on_line(None)
                self.session.set_on_close(None)
            except Exception:
                pass
        self.session = None
        self.loop = None

        await audit_log_ws(
            action="ws.disconnect",
            user=self.scope.get("user"),
            ip=self.ws_client_ip(self.scope),
            user_agent=self.ws_user_agent(self.scope),
            target_type="container",
            target_id=self.pk,
            message=f"WebSocket disconnected (code={code})",
            success=True,
        )

    # -------------------------
    # Event handlers
    # -------------------------
    def _on_line(self, line: str):
        """
        Thread-safe line forwarder from QemuSession -> WebSocket.
        Called in a non-async context; schedule coroutine on the event loop.
        """
        if not line or not line.strip():
            return
        loop = self.loop
        if not loop or not getattr(loop, "is_running", lambda: False)():
            return
        # Schedule the send on the loop thread-safely
        loop.call_soon_threadsafe(
            asyncio.create_task, self._send_json({"type": "log", "line": line})
        )

    def _on_close(self):
        """
        Notify client that the shell session closed (e.g., Ctrl+D).
        """
        loop = self.loop
        if not loop or not getattr(loop, "is_running", lambda: False)():
            return
        loop.call_soon_threadsafe(
            asyncio.create_task,
            self._send_json(
                {
                    "type": "info",
                    "message": "Shell closed (Ctrl+D). Use restart to reopen.",
                }
            ),
        )

    # -------------------------
    # Incoming messages
    # -------------------------
    async def receive_json(self, content, **kwargs):
        if not self.session:
            await self._send_json({"type": "error", "message": "No active session"})
            return

        action = content.get("action")
        data = content.get("data", "")

        if action == "restart":
            await self._restart_session()
            await self._send_to_session("ls -la")
            await audit_log_ws(
                action="ws.restart",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Shell restarted via WebSocket",
                success=True,
            )
            return

        await self._ensure_alive()

        # Ensure there is a live channel for any other command
        if action == "cmd":
            await self._send_to_session(data)
            await audit_log_ws(
                action="ws.cmd",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Command sent via WebSocket",
                metadata={"command": data[:200]},
                success=True,
            )
        elif action == "ctrlc":
            await self._send_to_session(CTRL_C)
            await audit_log_ws(
                action="ws.ctrlc",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Ctrl+C sent via WebSocket",
                success=True,
            )
        elif action == "ctrld":
            await self._send_to_session(CTRL_D)
            await audit_log_ws(
                action="ws.ctrld",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Ctrl+D sent via WebSocket",
                success=True,
            )
        elif action == "clear":
            await self._send_json({"type": "clear"})
            await audit_log_ws(
                action="ws.clear",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Clear requested via WebSocket",
                success=True,
            )
        else:
            await self._send_json(
                {"type": "error", "message": f"Unknown action: {action}"}
            )
            await audit_log_ws(
                action="ws.unknown",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Unknown WebSocket action",
                metadata={"action": action},
                success=False,
            )

    # -------------------------
    # Helpers
    # -------------------------
    async def _ensure_alive(self):
        """
        If the inner exec channel died, attempt to reopen it.
        """
        if self.session and not self.session.is_alive():
            await self._restart_session()

    async def _restart_session(self):
        """
        Reopen the shell channel without replacing the session object.
        """
        if not self.session:
            return
        try:
            await sync_to_async(self.session.reopen)()
            await self._send_json({"type": "info", "message": "Shell restarted"})
        except Exception as e:
            await self._send_json(
                {"type": "error", "message": "Failed to restart shell"}
            )
            await audit_log_ws(
                action="ws.restart",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Shell restart failed",
                metadata={"error": str(e)},
                success=False,
            )

    async def _send_json(self, obj: dict):
        """
        Consistent JSON writer; ensures ascii is not forced.
        """
        await self.send(text_data=json.dumps(obj, ensure_ascii=False))

    async def _send_to_session(self, text: str):
        """
        Proxy text to QemuSession in a thread-safe manner.
        """
        if not self.session or text is None:
            return
        try:
            await sync_to_async(self.session.send)(text)
        except Exception as e:
            await self._send_json(
                {"type": "error", "message": "Failed to send command"}
            )
            await audit_log_ws(
                action="ws.cmd",
                user=self.scope.get("user"),
                ip=self.ws_client_ip(self.scope),
                user_agent=self.ws_user_agent(self.scope),
                target_type="container",
                target_id=self.pk,
                message="Command send failed",
                metadata={"error": str(e), "text": text},
                success=False,
            )

    # -------------------------
    # ORM bridges (run in threadpool)
    # -------------------------
    @staticmethod
    @sync_to_async
    def _get_container(pk: int):
        container = apps.get_model("docker_manager", "Container")
        try:
            return container.objects.get(pk=pk)
        except container.DoesNotExist:
            return None

    @staticmethod
    @sync_to_async
    def _user_owns_container(pk: int, user_pk: int) -> bool:
        container = apps.get_model("docker_manager", "Container")
        return container.objects.filter(pk=pk, user_id=user_pk).exists()

    def ws_client_ip(self, scope) -> str:
        try:
            return scope.get("client", [None])[0] or ""
        except Exception:
            return ""

    def ws_user_agent(self, scope) -> str:
        try:
            for k, v in scope.get("headers", []):
                if k == b"user-agent":
                    return v.decode("utf-8", "ignore")
        except Exception:
            pass
        return ""
