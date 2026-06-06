from __future__ import annotations
from typing import Any, cast
from django.db import DatabaseError
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import User

from vm_manager.models import ResourceQuota, Container
from internal_config.models import AIUsageLog
from pequeroku.mixins import ContainerAccessMixin

from .minicode.frontends.pipeline import run_pipeline, agent, TokenUsage
from .minicode.prompts import INIT_PROMPT
from . import conversations as convo

# Mensajes en formato OpenAI (role/content/tool_calls/tool), tal como los produce
# y consume el motor minicode; se persisten verbatim en los archivos de la VM.
OpenAIChatMessage = dict[str, Any]


def _as_int(value: object) -> int | None:
    try:
        n = int(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


class AIConsumer(AsyncJsonWebsocketConsumer, ContainerAccessMixin):
    """Thin WebSocket consumer: authorization, client/model init, streaming.

    All agent logic (tool loops, schemas, system prompt) lives in app.agents.*
    """

    # Conversations live INSIDE the user's VM, one JSON file per conversation
    # under /app/.pequenin/ (see ai_services.conversations). All VM I/O goes
    # through ``convo`` (shared with the REST endpoint); here we just wrap the
    # sync helpers with sync_to_async and bind them to self.container_obj.

    @staticmethod
    @sync_to_async
    def _get_quota(user_id: int):
        try:
            quota = cast(ResourceQuota, ResourceQuota.objects.get(user_id=user_id))
            return quota, quota.ai_uses_left_today()
        except ResourceQuota.DoesNotExist:
            return None, None

    @staticmethod
    @sync_to_async
    def _set_quota(
        user: User,
        query: str,
        response: str,
        container: Container,
        token_usage: TokenUsage,
    ):
        AIUsageLog.objects.create(
            user=user,
            query=query,
            response=response,
            container=container,
            model_used=agent.model,
            prompt_tokens=token_usage.prompt_tokens,
            completion_tokens=token_usage.completion_tokens,
        )

    # -- conversation helpers (delegate to convo; resolved at call time so tests
    #    can monkeypatch ai_services.conversations) ---------------------------
    async def _get_memory(self, conversation_id: int) -> list[OpenAIChatMessage]:
        container = cast(Container, self.container_obj)
        return await sync_to_async(convo.read_conversation)(container, conversation_id)

    async def _set_memory(
        self, conversation_id: int, messages: list[OpenAIChatMessage]
    ) -> None:
        container = cast(Container, self.container_obj)
        await sync_to_async(convo.write_conversation)(
            container, conversation_id, messages
        )

    async def _list_conversation_ids(self) -> list[int]:
        container = cast(Container, self.container_obj)
        return await sync_to_async(convo.list_conversation_ids)(container)

    async def _get_current_id(self) -> int | None:
        container = cast(Container, self.container_obj)
        return await sync_to_async(convo.get_current_id)(self.user, container)

    async def _set_current_id(self, conversation_id: int) -> None:
        container = cast(Container, self.container_obj)
        await sync_to_async(convo.set_current_id)(self.user, container, conversation_id)

    async def _delete_conversation_file(self, conversation_id: int) -> None:
        container = cast(Container, self.container_obj)
        await sync_to_async(convo.delete_conversation)(container, conversation_id)

    async def _send_conversations(self, current: int) -> None:
        ids = await self._list_conversation_ids()
        if current not in ids:
            ids = sorted(set(ids + [current]))
        await self.send_json(
            {"event": "conversations", "conversations": ids, "current": current}
        )

    async def send_history(self, memory: list[OpenAIChatMessage]):
        for msg in memory:
            # Solo se muestran turnos de texto de user/assistant. Los mensajes de
            # tool y los assistant con tool_calls (sin texto) son traza interna.
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            if msg.get("tool_calls"):
                continue
            content = msg.get("content") or ""
            if len(content.strip()) == 0:
                continue

            await self.send_json({"event": "start_text", "role": role})
            await self.send_json(
                {
                    "event": "text",
                    "content": content,
                }
            )
            await self.send_json({"event": "finish_text"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages: list[OpenAIChatMessage] = []
        self.user: User | None = None
        self.user_pk: int = -1
        self.container_pk: int = -1
        self.container_obj: Container | None = None
        self.conversation_id: int = 1

    async def connect(self):
        self.user = cast(User | None, cast(object | None, self.scope.get("user", None)))

        if not self.user or self.user.is_anonymous:
            await self.close(code=4401)
            return

        await self.accept()

        self.user_pk = cast(int, self.user.pk)
        quota, ai_uses_left_today = await self._get_quota(self.user_pk)
        if quota is None or ai_uses_left_today is None or ai_uses_left_today <= 0:
            await self.send_json({"event": "start_text"})
            await self.send_json(
                {
                    "event": "text",
                    "content": "You have no available quota for today, try it tomorrow...",
                }
            )
            await self.send_json({"event": "finish_text"})
            await self.send_json(
                {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
            )
            await self.close(code=4401)
            return

        self.container_pk = cast(
            int, self.scope.get("url_route", {}).get("kwargs", {}).get("pk", -1)
        )
        try:
            allowed = await self._user_owns_container(self.container_pk, self.user_pk)
            if not allowed:
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        self.container_obj = await self._get_container_simple(self.container_pk)
        if not self.container_obj:
            await self.close(code=4404)
            return

        # Resume the last-used conversation (or the first one that exists, or a
        # fresh #1 if none) and replay its history.
        ids = await self._list_conversation_ids()
        current = await self._get_current_id()
        if current is None or current not in ids:
            current = ids[0] if ids else 1
        self.conversation_id = current
        self.messages = await self._get_memory(current)

        await self.send_history(self.messages)
        await self._send_conversations(current)

        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def _handle_action(self, action: str, content: dict[str, Any]) -> None:
        """Conversation management commands (do not consume AI quota)."""
        if not self.container_obj:
            return

        if action == "list_conversations":
            await self._send_conversations(self.conversation_id)
            return

        if action == "new_conversation":
            ids = await self._list_conversation_ids()
            new_id = (max(ids) + 1) if ids else 1
            self.conversation_id = new_id
            self.messages = []
            await self._set_memory(new_id, [])  # create the file so it lists
            await self._set_current_id(new_id)
            await self.send_json({"event": "clear"})
            await self._send_conversations(new_id)
            return

        if action == "switch_conversation":
            target = _as_int(content.get("id"))
            if target is None:
                return
            self.conversation_id = target
            self.messages = await self._get_memory(target)
            await self._set_current_id(target)
            await self.send_json({"event": "clear"})
            await self.send_history(self.messages)
            await self._send_conversations(target)
            return

        if action == "delete_conversation":
            target = _as_int(content.get("id"))
            if target is None:
                return
            await self._delete_conversation_file(target)
            ids = await self._list_conversation_ids()
            if self.conversation_id == target:
                self.conversation_id = ids[0] if ids else 1
                self.messages = await self._get_memory(self.conversation_id)
                await self._set_current_id(self.conversation_id)
                await self.send_json({"event": "clear"})
                await self.send_history(self.messages)
            await self._send_conversations(self.conversation_id)
            return

    async def receive_json(self, content: dict[str, str], **kwargs: dict[str, Any]):
        async def send_text(text: str):
            await self.send_json({"event": "start_text"})
            await self.send_json(
                {
                    "event": "text",
                    "content": text,
                }
            )
            await self.send_json({"event": "finish_text"})

        async def on_tool_call(tool: str, **kwargs: dict[str, Any]):
            print(f"[on_tool_call] using: {tool} with {kwargs}")
            await send_text(f"Using {tool}...")

        async def on_start_chunk():
            await self.send_json({"event": "start_text"})

        async def on_chunk(chunk: str):
            await self.send_json({"event": "text", "content": chunk})

        async def on_finish(response: str):
            # Set Quota
            if not self.container_obj or not self.user:
                return
            print(f"[on_finish] {response}")
            await self.send_json({"event": "finish_text"})

        async def on_event(payload: dict[str, Any]):
            # Structured view of what the agent is doing internally: tool calls
            # (with args + the synthesized command), tool results/output, todo
            # updates, subagent start/finish, info/error notices and per-step token
            # usage. Emitted as one WS message per event; the event name is the
            # payload "type" so the client can switch on it (it may ignore them).
            try:
                event_type = str(payload.get("type") or "agent_event")
                fields = {k: v for k, v in payload.items() if k != "type"}
                await self.send_json({"event": event_type, **fields})
            except Exception:
                pass

        # Conversation management (list / new / switch / delete) — no quota cost.
        action = content.get("action")
        if action:
            if not self.container_obj or not self.user:
                return
            await self._handle_action(str(action), cast(dict[str, Any], content))
            return

        user_text = content.get("text", "")[:3000]
        if not user_text.strip():
            return

        if not agent or not self.container_obj or not self.user:
            print("[AGENT]: Not agent found")
            return

        quota, ai_uses_left_today = await self._get_quota(self.user_pk)
        if quota is None or ai_uses_left_today is None or ai_uses_left_today <= 0:
            await send_text("You have no available quota for today, try it tomorrow...")
            await self.close(code=4401)
            return

        if user_text == "/clear":
            await self.send_json({"event": "clear"})
            await send_text("Memory clear...")
            self.messages = []
            await self._set_memory(self.conversation_id, self.messages)
            return

        # /init: run a normal AI turn (consumes quota) whose instruction is the
        # canned prompt that creates or improves /app/AGENTS.md.
        if user_text == "/init":
            user_text = INIT_PROMPT

        await self.send_json({"event": "start_text"})
        await self.send_json({"event": "text", "content": "..."})

        # Process LLM
        self.messages, token_usage = await run_pipeline(
            query=user_text,
            messages=self.messages,
            container_obj=self.container_obj,
            on_chunk=on_chunk,
            on_tool_call=on_tool_call,
            on_start_chunking=on_start_chunk,
            on_finish_chunking=on_finish,
            on_event=on_event,
        )

        await self._set_quota(
            self.user,
            user_text,
            self.messages[-1]["content"],
            self.container_obj,
            token_usage,
        )
        await self.send_json(
            {
                "event": "memory_data",
                "memory": self.messages,
                "conversation": self.conversation_id,
            }
        )
        await self._set_memory(self.conversation_id, self.messages)

        quota, ai_uses_left_today = await self._get_quota(self.user_pk)
        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def disconnect(self, code: int):
        pass
