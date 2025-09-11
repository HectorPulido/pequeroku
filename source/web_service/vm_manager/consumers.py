import json
import asyncio
import contextlib
from asyncio.events import AbstractEventLoop
from typing import Optional

from channels.generic.websocket import AsyncJsonWebsocketConsumer
import websockets
from django.apps import apps
from django.db import DatabaseError

from internal_config.audit import audit_log_ws

from asgiref.sync import sync_to_async


class ConsoleConsumer(AsyncJsonWebsocketConsumer):
    """
    Client <-> Django <-> FastAPI
    """

    @staticmethod
    @sync_to_async
    def _user_owns_container(pk: int, user_pk: int) -> bool:
        user_mod = apps.get_model("auth", "User")

        user = user_mod.objects.get(pk=user_pk)
        if user.is_superuser:
            return True

        container = apps.get_model("vm_manager", "Container")
        return container.objects.filter(pk=pk, user_id=user_pk).exists()

    def _ws_client_ip(self, scope) -> str:
        try:
            return scope.get("client", [None])[0] or ""
        except Exception:
            return ""

    def _ws_user_agent(self, scope) -> str:
        try:
            for k, v in scope.get("headers", []):
                if k == b"user-agent":
                    return v.decode("utf-8", "ignore")
        except Exception:
            pass
        return ""

    async def _send_json(self, obj: dict):
        """
        Consistent JSON writer; ensures ascii is not forced.
        """
        await self.send(text_data=json.dumps(obj, ensure_ascii=False))

    @staticmethod
    @sync_to_async
    def _get_container(pk: int):
        container = apps.get_model("vm_manager", "Container")

        container_obj = None
        try:
            container_obj = container.objects.get(pk=pk)
        except container.DoesNotExist:
            return None

        return container_obj, container_obj.node

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.loop: Optional[AbstractEventLoop] = None
        self.session = None

    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        self.loop = asyncio.get_running_loop()

        try:
            allowed = await self._user_owns_container(self.pk, self.scope["user"].pk)
            if not allowed:
                await audit_log_ws(
                    action="ws.connect",
                    user=self.scope["user"],
                    ip=self._ws_client_ip(self.scope),
                    user_agent=self._ws_user_agent(self.scope),
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

        container_obj, node = await self._get_container(self.pk)
        if not container_obj or not node:
            await audit_log_ws(
                action="ws.connect",
                user=self.scope["user"],
                ip=self._ws_client_ip(self.scope),
                user_agent=self._ws_user_agent(self.scope),
                target_type="container",
                target_id=str(self.pk),
                message="WebSocket connect failed: container not found",
                success=False,
            )
            await self.close(code=4404)
            return

        await self._send_json({"type": "info", "message": "Connected"})

        container_node_host: str = node.node_host
        container_node_host = container_node_host.replace("http://", "ws://")
        container_node_host = container_node_host.replace("https://", "wss://")

        container_id = container_obj.container_id

        upstream_url = f"{container_node_host}vms/{container_id}/tty"
        try:
            custom_headers = {
                "Authorization": f"Bearer {node.auth_token}",
            }
            self.upstream = await websockets.connect(
                upstream_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                additional_headers=custom_headers,
            )
        except Exception as e:
            await self.send(text_data=f"Proxy error: could not connect ({e})")
            await self.close()
            return

        self.reader_task = asyncio.create_task(self._pump_upstream_to_client())

        await asyncio.sleep(1)
        await self.upstream.send("cd /app\n")
        await asyncio.sleep(0.25)
        await self.upstream.send("clear\n")
        await asyncio.sleep(0.25)
        await self.upstream.send("ls -la\n")

    async def receive(self, text_data=None, bytes_data=None):
        if not hasattr(self, "upstream"):
            await self.send(text_data="Proxy: closed upstream")
            await self.close()
            return

        if text_data is not None:
            if not text_data.endswith("\n"):
                text_data += "\n"
            try:
                await self.upstream.send(text_data)
            except Exception as e:
                await self.send(text_data=f"Proxy error when sending upstream: {e}")
                await self.close()
        elif bytes_data is not None:
            try:
                await self.upstream.send(bytes_data)
            except Exception as e:
                await self.send(text_data=f"Proxy error when sending bin upstream: {e}")
                await self.close()

    async def disconnect(self, code):
        with contextlib.suppress(Exception):
            if hasattr(self, "reader_task"):
                self.reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.reader_task
        with contextlib.suppress(Exception):
            if hasattr(self, "upstream"):
                await self.upstream.close()

    async def _pump_upstream_to_client(self):
        try:
            async for msg in self.upstream:
                if isinstance(msg, (bytes, bytearray)):
                    await self.send(bytes_data=msg)
                else:
                    await self.send(text_data=msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            with contextlib.suppress(Exception):
                await self.send(text_data=f"Proxy: upstream conection ended ({e})")
        finally:
            with contextlib.suppress(Exception):
                await self.close()
