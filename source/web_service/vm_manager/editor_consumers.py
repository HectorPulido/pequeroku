from __future__ import annotations
import shlex
import re
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.apps import apps
from django.db import DatabaseError
from asgiref.sync import sync_to_async

from internal_config.audit import audit_log_ws  # TODO
from pequeroku.redis import VersionStore
from .vm_client import VMServiceClient, VMUploadFiles, VMFile
from .models import Container, Node

from .templates import first_start_of_container

SAFE_ROOT = "/app"
_path_norm = lambda p: re.sub(r"/+", "/", p or "").rstrip("/") or "/"


class EditorConsumer(AsyncJsonWebsocketConsumer):

    async def _bump_rev(self, cid: str, p: str) -> int:
        return await VersionStore.bump_rev(cid=cid, path=p)

    async def _get_rev(self, cid: str, p: str) -> int:
        return await VersionStore.get_rev(cid=cid, path=p)

    @sync_to_async
    def _first_start_of_container(
        self,
    ):
        first_start_of_container(self.container)

    @staticmethod
    @sync_to_async
    def _user_owns_container(pk: int, user_pk: int) -> bool:
        User = apps.get_model("auth", "User")
        user = User.objects.get(pk=user_pk)
        if user.is_superuser:
            return True
        ContainerM = apps.get_model("vm_manager", "Container")
        return ContainerM.objects.filter(pk=pk, user_id=user_pk).exists()

    @staticmethod
    @sync_to_async
    def _get_container(pk: int):
        ContainerM = apps.get_model("vm_manager", "Container")
        try:
            obj = ContainerM.objects.select_related("node").get(pk=pk)
            return obj, obj.node
        except ContainerM.DoesNotExist:
            return None, None

    def _service(self, container: Container) -> VMServiceClient:
        node: Node = container.node
        return VMServiceClient(base_url=str(node.node_host), token=str(node.auth_token))

    def _group_name(self, pk: int) -> str:
        return f"container-fs-{pk}"

    def _check_path(self, p: str) -> str:
        p = _path_norm(p)
        if not p.startswith(SAFE_ROOT):
            raise ValueError("path must be under /app")
        return p

    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        try:
            allowed = await self._user_owns_container(self.pk, self.scope["user"].pk)
            if not allowed:
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        await self.accept()
        self.container, self.node = await self._get_container(self.pk)
        if not self.container:
            await self.close(code=4404)
            return

        self.client = self._service(self.container)
        self.container_id = str(self.container.container_id)

        await self._first_start_of_container()

        await self.channel_layer.group_add(self._group_name(self.pk), self.channel_name)
        await self.send_json({"event": "connected"})

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(
                self._group_name(self.pk), self.channel_name
            )
        except Exception:
            pass

    async def receive_json(self, content, **kwargs):
        req_id = content.get("req_id")
        action = (content.get("action") or "").strip()
        try:
            if action == "list_dir":
                await self._handle_list_dir(content, req_id)
            elif action == "read_file":
                await self._handle_read_file(content, req_id)
            elif action == "create_dir":
                await self._handle_create_dir(content, req_id)
            elif action == "write_file":
                await self._handle_write_file(content, req_id)
            elif action == "move_path":
                await self._handle_move_path(content, req_id)
            elif action == "delete_path":
                await self._handle_delete_path(content, req_id)
            else:
                await self.send_json(
                    {
                        "event": "error",
                        "req_id": req_id,
                        "error": f"unknown action: {action}",
                    }
                )
        except Exception as e:
            await self.send_json({"event": "error", "req_id": req_id, "error": str(e)})

    async def ws_broadcast(self, event):
        await self.send_json(event["payload"])

    async def _handle_list_dir(self, content, req_id):
        path = self._check_path(content.get("path") or "/app")
        data = self.client.list_dir(self.container_id, path)
        await self.send_json(
            {
                "event": "ok",
                "req_id": req_id,
                "data": {"entries": data, "path": path},
            }
        )
        await audit_log_ws(
            action="container.list_dir",
            target_type="container",
            target_id=self.container_id,
            message="Directory listed via find",
            metadata={"root": path, "count": len(data)},
            success=True,
        )

    async def _handle_read_file(self, content, req_id):
        path = self._check_path(content["path"])
        data = self.client.read_file(self.container_id, path)

        data["rev"] = await self._get_rev(self.container_id, path)
        await self.send_json({"event": "ok", "req_id": req_id, "data": data})

        await audit_log_ws(
            action="container.read_file",
            target_type="container",
            target_id=self.container_id,
            message="File read via SFTP",
            metadata={"path": path, "bytes_read": data.get("length", 0)},
            success=True,
        )

    async def _handle_create_dir(self, content, req_id):
        path = self._check_path(content["path"])
        self.client.create_dir(self.container_id, path)

        r = await self._bump_rev(self.container_id, path)
        await self.channel_layer.group_send(
            self._group_name(self.pk),
            {
                "type": "ws.broadcast",
                "payload": {
                    "event": "file_changed",
                    "path": path,
                    "rev": r,
                    "meta": {"op": "create_dir"},
                },
            },
        )
        await self.send_json({"event": "ok", "req_id": req_id})

        await audit_log_ws(
            action="container.create_dir",
            target_type="container",
            target_id=self.container_id,
            message="Directory created",
            metadata={"path": path},
            success=True,
        )

    async def _handle_write_file(self, content, req_id):
        path = self._check_path(content["path"])
        prev = int(content.get("prev_rev") or 0)
        cur = await self._get_rev(self.container_id, path)
        if prev and prev != cur:
            return await self.send_json(
                {
                    "event": "error",
                    "req_id": req_id,
                    "error": "conflict",
                    "rev": cur,
                }
            )
        self.client.upload_files(
            self.container_id,
            VMUploadFiles(
                dest_path="/",
                clean=False,
                files=[VMFile(path=path, text=content.get("content", ""))],
            ),
        )
        r = await self._bump_rev(self.container_id, path)
        await self.channel_layer.group_send(
            self._group_name(self.pk),
            {
                "type": "ws.broadcast",
                "payload": {
                    "event": "file_changed",
                    "path": path,
                    "rev": r,
                    "meta": {
                        "op": "write_file",
                        "bytes": len(content.get("content", "")),
                    },
                },
            },
        )
        await self.send_json({"event": "ok", "req_id": req_id, "rev": r})

        await audit_log_ws(
            action="container.write_file",
            target_type="container",
            target_id=self.container_id,
            message="File written via SFTP",
            metadata={"path": path, "bytes": len(content or "")},
            success=True,
        )

    async def _handle_move_path(self, content, req_id):
        src = self._check_path(content["src"])
        dst = self._check_path(content["dst"])
        cmd = f"set -e; mv -f {shlex.quote(src)} {shlex.quote(dst)}"
        resp = self.client.execute_sh(self.container_id, cmd)
        r = await self._bump_rev(self.container_id, dst)
        await self.channel_layer.group_send(
            self._group_name(self.pk),
            {
                "type": "ws.broadcast",
                "payload": {
                    "event": "path_moved",
                    "src": src,
                    "dst": dst,
                    "rev": r,
                },
            },
        )
        await self.send_json({"event": "ok", "req_id": req_id, "rev": r})

        await audit_log_ws(
            action="container.change_path",
            target_type="container",
            target_id=self.container_id,
            message="Deletion success",
            metadata={"src": src, "dest": dst, "response": resp},
            success=True,
        )

    async def _handle_delete_path(self, content, req_id):
        path = self._check_path(content["path"])
        recursive = bool(content.get("recursive"))
        cmd = f"set -e; rm {'-rf' if recursive else ''} {shlex.quote(path)}"
        resp = self.client.execute_sh(self.container_id, cmd)
        r = await self._bump_rev(self.container_id, path)
        await self.channel_layer.group_send(
            self._group_name(self.pk),
            {
                "type": "ws.broadcast",
                "payload": {"event": "path_deleted", "path": path, "rev": r},
            },
        )
        await self.send_json({"event": "ok", "req_id": req_id, "rev": r})

        await audit_log_ws(
            action="container.delete_file",
            target_type="container",
            target_id=self.container_id,
            message="Deletion success",
            metadata={"path": path, "response": resp},
            success=True,
        )
