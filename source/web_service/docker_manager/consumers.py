# docker_manager/consumers.py
from asyncio.events import AbstractEventLoop
import asyncio
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.apps import apps
from django.conf import settings
from asgiref.sync import sync_to_async
from django.db import DatabaseError
from .session import DockerSession
from .views import SESSIONS

CTRL_C = "\x03"
CTRL_D = "\x04"


class ConsoleConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *argv, **kwargs):
        super().__init__(*argv, **kwargs)
        self.pk = -1
        self.loop: "AbstractEventLoop" | None = None
        self.session: "DockerSession" | None = None

    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        self.loop = asyncio.get_running_loop()

        # ORM en hilo
        try:
            if not await self._user_owns_container(self.pk, self.scope["user"].pk):
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        await self.accept()
        await self._send_json({"type": "info", "message": "Connected"})

        # obtener/crear sesión
        self.session = SESSIONS.get(self.pk)
        if not self.session:
            container_obj = await self._get_container(self.pk)
            if not container_obj:
                await self.close(code=4404)
                return
            self.session = await sync_to_async(
                lambda: DockerSession(
                    container_obj,
                    settings.DOCKER_CLIENT,
                    on_line=self._on_line,
                    on_close=self._on_close,
                )
            )()
            SESSIONS[self.pk] = self.session
        else:
            self.session.set_on_line(self._on_line)
            self.session.set_on_close(self._on_close)

        # Auto “ls” al entrar (si el exec está vivo)
        await self._ensure_alive()
        await self._send_to_session("ls -la")

    def _on_line(self, line: str):
        if not line.strip():
            return
        if not self.loop:
            return
        if hasattr(self, "loop") and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                asyncio.create_task, self._send_json({"type": "log", "line": line})
            )

    def _on_close(self):
        # Notifica al cliente que la sesión se cerró
        if not self.loop:
            return

        if hasattr(self, "loop") and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                asyncio.create_task,
                self._send_json(
                    {
                        "type": "info",
                        "message": "Shell closed (Ctrl+D). Use restart to reopen.",
                    }
                ),
            )

    async def receive_json(self, content, **kwargs):
        if not self.session:
            await self._send_json({"type": "error", "message": "No active session"})
            return

        action = content.get("action")
        data = content.get("data", "")

        if action == "restart":
            await self._restart_session()
            await self._send_to_session("ls -la")
            return

        # Para cualquier comando, si está muerto, reabre automáticamente
        await self._ensure_alive()

        if action == "cmd":
            await self._send_to_session(data)
        elif action == "ctrlc":
            await self._send_to_session(CTRL_C)
        elif action == "ctrld":
            await self._send_to_session(CTRL_D)
        elif action == "clear":
            await self._send_json({"type": "clear"})
        else:
            await self._send_json(
                {"type": "error", "message": f"Unknown action: {action}"}
            )

    async def disconnect(self, code):
        if not self.session:
            return
        self.session.set_on_line(None)
        self.session.set_on_close(None)

    # ----- helpers -----
    async def _ensure_alive(self):
        if self.session and not self.session.is_alive():
            await self._restart_session()

    async def _restart_session(self):
        if not self.session:
            return

        await sync_to_async(self.session.reopen)()
        await self._send_json({"type": "info", "message": "Shell restarted"})

    async def _send_json(self, obj):
        await self.send(text_data=json.dumps(obj, ensure_ascii=False))

    async def _send_to_session(self, text: str):
        if not self.session:
            return
        await sync_to_async(self.session.send)(text)

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
