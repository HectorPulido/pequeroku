from __future__ import annotations
import shlex
import re
import asyncio
from datetime import datetime
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import DatabaseError
from asgiref.sync import sync_to_async

from pequeroku.mixins import ContainerAccessMixin, AuditMixin
from pequeroku.redis import VersionStore
from .vm_client import VMServiceClient, VMUploadFiles, VMFile, SearchRequest
from .models import Container
from .templates import first_start_of_container

SAFE_ROOT = "/app"
_path_norm = lambda p: re.sub(r"/+", "/", p or "").rstrip("/") or "/"


class EditorConsumer(
    AsyncJsonWebsocketConsumer,
    ContainerAccessMixin,
    AuditMixin,
):
    async def _bump_rev(self, cid: str, p: str) -> int:
        return await VersionStore.bump_rev(cid=cid, path=p)

    async def _get_rev(self, cid: str, p: str) -> int:
        return await VersionStore.get_rev(cid=cid, path=p)

    @sync_to_async
    def _first_start_of_container(self):
        first_start_of_container(self.container)

    def _check_path(self, p: str) -> str:
        p = _path_norm(p)
        if not p.startswith(SAFE_ROOT):
            raise ValueError("path must be under /app")
        return p

    @sync_to_async
    def _service(self, container: Container) -> VMServiceClient:
        return VMServiceClient(container.node)

    def _group_name(self, pk: int) -> str:
        return f"container-fs-{pk}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.user = None
        self.container = None
        self.node = None
        self.client = None
        self.container_id = ""
        self._watcher_task = None
        self._last_digest = None

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        try:
            allowed = await self._user_owns_container(self.pk, self.user.pk)
            if not allowed:
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        await self.accept()
        self.container, self.node = await self._get_container_with_node(
            self.pk, use_select_related=True
        )
        if not self.container:
            await self.close(code=4404)
            return

        self.client = await self._service(self.container)
        self.container_id = str(self.container.container_id)

        await self._first_start_of_container()

        await self.channel_layer.group_add(self._group_name(self.pk), self.channel_name)
        await self.send_json({"event": "connected"})
        # self._start_fs_watcher()

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(
                self._group_name(self.pk), self.channel_name
            )
        except Exception:
            pass
        # await self._stop_fs_watcher()

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
            elif action == "search":
                await self._handle_search(content, req_id)
            else:
                await self.send_json(
                    {
                        "event": "error",
                        "req_id": req_id,
                        "error": f"unknown action: {action}",
                    }
                )
        except Exception as e:
            print("Error receive_json: ", e)
            await self.send_json({"event": "error", "req_id": req_id, "error": str(e)})

    async def ws_broadcast(self, event):
        await self.send_json(event["payload"])

    async def _handle_list_dir(self, content, req_id):
        path = self._check_path(content.get("path") or "/app")
        if not self.client:
            return
        data = self.client.list_dir(self.container_id, path)
        await self.send_json(
            {
                "event": "ok",
                "req_id": req_id,
                "data": {"entries": data, "path": path},
            }
        )
        await self.audit_ws(
            user=self.user,
            action="container.list_dir",
            target_type="container",
            target_id=self.container_id,
            message="Directory listed via find",
            metadata={"root": path, "count": len(data)},
            success=True,
        )

    async def _handle_read_file(self, content, req_id):
        path = self._check_path(content["path"])
        if not self.client:
            return
        data = self.client.read_file(self.container_id, path)

        data["rev"] = await self._get_rev(self.container_id, path)
        await self.send_json({"event": "ok", "req_id": req_id, "data": data})

        await self.audit_ws(
            user=self.user,
            action="container.read_file",
            target_type="container",
            target_id=self.container_id,
            message="File read via SFTP",
            metadata={"path": path, "bytes_read": data.get("length", 0)},
            success=True,
        )

    async def _handle_search(self, content, req_id):
        root = self._check_path(content["root"])
        pattern = content["pattern"]
        if not self.client:
            return

        search = self.client.search(
            str(self.container_id),
            SearchRequest(
                pattern=pattern,
                root=root,
                case_insensitive=False,
                max_results_total=250,
                timeout_seconds=5,
            ),
        )
        await self.send_json({"event": "ok", "req_id": req_id, "data": search})
        await self.audit_ws(
            user=self.user,
            action="container.read_file",
            target_type="container",
            target_id=self.container_id,
            message="Search",
            metadata={"root": root, "pattern": pattern, "response": search},
            success=True,
        )

    async def _handle_create_dir(self, content, req_id):
        path = self._check_path(content["path"])
        if not self.client:
            return
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

        await self.audit_ws(
            user=self.user,
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
        if not self.client:
            return
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

        await self.audit_ws(
            user=self.user,
            action="container.write_file",
            target_type="container",
            target_id=self.container_id,
            message="File written via SFTP",
            metadata={"path": path, "bytes": len(content or "")},
            success=True,
        )

    async def _handle_move_path(self, content, req_id):
        path_src = self._check_path(content["src"])
        path_dst = self._check_path(content["dst"])
        cmd = f"set -e; mv -f {shlex.quote(path_src)} {shlex.quote(path_dst)}"
        if not self.client:
            return
        resp = self.client.execute_sh(self.container_id, cmd)
        r = await self._bump_rev(self.container_id, path_dst)
        await self.channel_layer.group_send(
            self._group_name(self.pk),
            {
                "type": "ws.broadcast",
                "payload": {
                    "event": "path_moved",
                    "src": path_src,
                    "dst": path_dst,
                    "rev": r,
                },
            },
        )
        await self.send_json({"event": "ok", "req_id": req_id, "rev": r})

        await self.audit_ws(
            user=self.user,
            action="container.change_path",
            target_type="container",
            target_id=self.container_id,
            message="Move success",
            metadata={"src": path_src, "dest": path_dst, "response": resp},
            success=True,
        )

    async def _handle_delete_path(self, content, req_id):
        path = self._check_path(content["path"])
        cmd = f"set -e; rm -rf {shlex.quote(path)}"
        if not self.client:
            return
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

        await self.audit_ws(
            user=self.user,
            action="container.delete_file",
            target_type="container",
            target_id=self.container_id,
            message="Deletion success",
            metadata={"path": path, "response": resp},
            success=True,
        )

    async def _fs_digest(self, root: str = SAFE_ROOT) -> str:
        root = self._check_path(root)
        cmd = (
            f"set -e; dir={shlex.quote(root)}; "
            r"find $dir -not -path '*/.git/*' -printf '%y|%P|%s|%T@\n' "
            r"| sort | sha256sum | cut -d' ' -f1"
        )
        if not self.client:
            return ""
        out = self.client.execute_sh(self.container_id, cmd)
        return out["reason"]

    async def _get_fs_digest_cached(self, path: str) -> str | None:
        try:
            return await VersionStore.get_rev(
                cid=self.container_id, path=f"__fs_digest__:{path}"
            )
        except Exception:
            return None

    async def _set_fs_digest_cached(self, path: str, digest: str) -> None:
        try:
            await VersionStore.bump_rev(
                cid=self.container_id, path=f"__fs_digest__:{path}"
            )
        except Exception:
            pass

    # watcher principal
    async def _watch_fs_loop(self, path: str = SAFE_ROOT, interval: float = 1.0):
        try:
            last = self._last_digest or await self._get_fs_digest_cached(path)
            while True:
                try:
                    cur = await self._fs_digest(path)
                    if cur and cur != last:
                        ts = datetime.utcnow().isoformat() + "Z"
                        await self.channel_layer.group_send(
                            self._group_name(self.pk),
                            {
                                "type": "ws.broadcast",
                                "payload": {
                                    "event": "fs_changed",
                                    "path": path,
                                    "ts": ts,
                                },
                            },
                        )
                        self._last_digest = cur
                        await self._set_fs_digest_cached(path, cur)
                        last = cur
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await asyncio.sleep(interval)
        finally:
            pass

    def _start_fs_watcher(self):
        if self._watcher_task is None or self._watcher_task.done():
            self._watcher_task = asyncio.create_task(
                self._watch_fs_loop(SAFE_ROOT, 2.0)
            )

    async def _stop_fs_watcher(self):
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        self._watcher_task = None
