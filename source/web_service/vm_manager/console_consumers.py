import asyncio
import contextlib
from typing import Optional
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
        self.session = None
        self.user = None

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

        container_obj, node = await self._get_container_with_node(self.pk)
        if not container_obj or not node:
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

        await self.send_json_safe({"type": "info", "message": "Connected"})

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

            await self.audit_ws(
                action="ws.cmd",
                user=self.user,
                target_type="container",
                target_id=str(self.pk),
                message=text_data,
                success=True,
            )

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
