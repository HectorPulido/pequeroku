from __future__ import annotations
import shlex
import re
import asyncio
from typing import cast
from datetime import datetime
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import DatabaseError
from asgiref.sync import sync_to_async

from pequeroku.mixins import ContainerAccessMixin, AuditMixin
from pequeroku.redis import VersionStore
from .vm_client import VMServiceClient, VMUploadFiles, VMFile, SearchRequest
from .templates import first_start_of_container
from .models import Container, Node


SAFE_ROOT = "/app"


def _path_norm(p: str):
    return re.sub(r"/+", "/", p or "").rstrip("/") or "/"


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
        if not self.container:
            return None

        first_start_of_container(self.container)

    def _check_path(self, p: str) -> str:
        p = _path_norm(p)
        if not p.startswith(SAFE_ROOT):
            raise ValueError("path must be under /app")
        return p

    @sync_to_async
    def _service(self, container: Container) -> VMServiceClient:
        return VMServiceClient(cast(Node, container.node))

    def _group_name(self, pk: int) -> str:
        return f"container-fs-{pk}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pk: int = -1
        self.user: object | None = None
        self.container: Container | None = None
        self.node: Node | None = None
        self.client: VMServiceClient | None = None
        self.container_id: str = ""
        self._watcher_task = None
        self._last_digest = None

    async def connect(self):
        self.user = self.scope.get("user", None)
        if not self.user or self.user.is_anonymous:
            await self.close(code=4401)
            return

        self.pk = int(
            cast(str, self.scope.get("url_route", {}).get("kwargs", {}).get("pk", "-1"))
        )
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

    async def receive_json(self, content: dict[str, str], **kwargs):
        req_id = int(content.get("req_id", "-1"))
        action = (content.get("action") or "").strip()
        try:
            if action == "list_dirs":
                await self._handle_list_dirs(content, req_id)
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

    async def ws_broadcast(self, event: dict[str, list[str] | dict[str, str]]) -> None:
        await self.send_json(event["payload"])

    async def _handle_list_dirs(self, content: dict[str, str], req_id: int) -> None:
        paths: list[str] = [
            self._check_path(path or "/app")
            for path in content.get("path", "").split(",")
        ]

        if not self.client:
            return
        data = self.client.list_dirs(self.container_id, paths)
        await self.send_json(
            {
                "event": "ok",
                "req_id": req_id,
                "data": {"entries": data, "path": paths},
            }
        )
        await self.audit_ws(
            user=self.user,
            action="container.list_dir",
            target_type="container",
            target_id=self.container_id,
            message="Multiple directory listed via list",
            metadata={"paths": paths, "count": len(data)},
            success=True,
        )

    async def _handle_read_file(self, content: dict[str, str], req_id: int) -> None:
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

    async def _handle_search(self, content: dict[str, str], req_id: int) -> None:
        root = self._check_path(content["root"])
        pattern = content["pattern"]
        case_sensitive = bool(content.get("case", "false") == "true")
        include_globs = content.get("include_globs", "").split(",")
        exclude_dirs = content.get("exclude_dirs", "").split(",")

        if not self.client:
            return

        search = self.client.search(
            str(self.container_id),
            SearchRequest(
                pattern=pattern,
                root=root,
                case_insensitive=case_sensitive,
                include_globs=include_globs,
                exclude_dirs=exclude_dirs,
                max_results_total=250,
                timeout_seconds=10,
            ).apply_exclude_diff(),
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

    async def _handle_create_dir(self, content: dict[str, str], req_id: int) -> None:
        path: str = self._check_path(content["path"])
        if not self.client:
            return
        _ = self.client.create_dir(self.container_id, path)

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

    async def _handle_write_file(self, content: dict[str, str], req_id: int) -> None:
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
        _ = self.client.upload_files(
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

    async def _handle_move_path(self, content: dict[str, str], req_id: int) -> None:
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

    async def _handle_delete_path(self, content: dict[str, str], req_id: int) -> None:
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
            r"find \"$dir\" \( -path '*/.git/*' -o -path '*/.cache/*' -o -path '*/node_modules/*' \) -prune -o -printf '%y|%P|%s|%T@\n' "
            r"| sort | sha256sum | cut -d' ' -f1"
        )
        if not self.client:
            return ""
        out = self.client.execute_sh(self.container_id, cmd)
        return cast(str, out["reason"])

    async def _get_fs_digest_cached(self, path: str) -> str | int | None:
        try:
            return await VersionStore.get_rev(
                cid=self.container_id, path=f"__fs_digest__:{path}"
            )
        except Exception:
            return None

    async def _set_fs_digest_cached(self, path: str) -> None:
        try:
            _ = await VersionStore.bump_rev(
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
                        await self._set_fs_digest_cached(path)
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
                self._watch_fs_loop(SAFE_ROOT, 5.0)
            )

    async def _stop_fs_watcher(self):
        if self._watcher_task and not self._watcher_task.done():
            _ = self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        self._watcher_task = None
