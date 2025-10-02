from __future__ import annotations
from typing import Any, cast
from django.db import DatabaseError
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.apps import apps
from django.contrib.auth.models import User

from vm_manager.models import ResourceQuota, Container
from internal_config.models import Config, AIMemory
from pequeroku.mixins import ContainerAccessMixin

from .agents import OpenAIChatMessage, TokenUsage
from .ai_engineer import agent


class AIConsumer(AsyncJsonWebsocketConsumer, ContainerAccessMixin):
    """Thin WebSocket consumer: authorization, client/model init, streaming.

    All agent logic (tool loops, schemas, system prompt) lives in app.agents.*
    """

    @staticmethod
    @sync_to_async
    def _get_quota(user_id: int):
        resource_quota_mod = apps.get_model("vm_manager", "ResourceQuota")
        try:
            quota = cast(ResourceQuota, resource_quota_mod.objects.get(user_id=user_id))
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
        ai_usage_log_model = apps.get_model("internal_config", "AIUsageLog")
        ai_usage_log_model.objects.create(
            user=user,
            query=query,
            response=response,
            container=container,
            model_used=agent.model,
            prompt_tokens=token_usage["prompt_tokens"],
            completion_tokens=token_usage["completion_tokens"],
        )

    @staticmethod
    @sync_to_async
    def _set_memory(
        user: User, container: Container, memory_data: list[OpenAIChatMessage]
    ):
        ai_memory = apps.get_model("internal_config", "AIMemory")
        memory, created = cast(
            tuple[AIMemory, bool],
            ai_memory.objects.get_or_create(
                user=user, container=container, defaults={"memory": memory_data}
            ),
        )

        if not created:
            memory.memory = memory_data
            memory.save()

    @staticmethod
    @sync_to_async
    def _get_memory(user: User, container: Container) -> list[OpenAIChatMessage]:
        ai_memory = apps.get_model("internal_config", "AIMemory")
        memory = cast(
            AIMemory | None,
            ai_memory.objects.filter(
                user=user,
                container=container,
            ).last(),
        )
        if not memory:
            return []
        return cast(list[OpenAIChatMessage], memory.memory)

    @staticmethod
    @sync_to_async
    def _get_config_values():
        return Config.get_config_values(
            ["openai_api_key", "openai_api_url", "openai_model"]
        )

    async def send_history(self, memory: list[OpenAIChatMessage]):
        for i, msg in enumerate(memory):
            if msg["role"] in ("function", "system"):
                continue

            if msg["content"].startswith(
                "Some useful information to respond to the user query:"
            ):
                continue
            if len(msg["content"].strip()) == 0:
                continue

            await self.send_json({"event": "start_text", "role": msg["role"]})
            await self.send_json(
                {
                    "event": "text",
                    "content": msg["content"],
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

        self.messages = await self._get_memory(self.user, self.container_obj)

        await self.send_history(self.messages)

        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def receive_json(self, content: dict[str, str], **kwargs):
        user_text = content.get("text", "")[:3000]
        if not user_text.strip():
            return

        if not agent or not self.container_obj or not self.user:
            print("[AGENT]: Not agent found")
            return

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

        async def on_chunk(chunk: str):
            await self.send_json({"event": "text", "content": chunk})

        async def on_finish(response: str):
            # Set Quota
            if not self.container_obj or not self.user:
                return
            print(f"[on_finish] {response}")
            await self.send_json({"event": "finish_text"})

        quota, ai_uses_left_today = await self._get_quota(self.user_pk)
        if quota is None or ai_uses_left_today is None or ai_uses_left_today <= 0:
            await send_text("You have no available quota for today, try it tomorrow...")
            await self.close(code=4401)
            return

        if user_text == "/clear":
            await send_text("Memory clear...")
            self.messages = []
            await self._set_memory(self.user, self.container_obj, self.messages)
            return

        await self.send_json({"event": "start_text"})
        await self.send_json({"event": "text", "content": "..."})

        # Process LLM
        self.messages.append({"role": "user", "content": user_text})

        self.messages, t_u = await agent.run_tool_loop(
            self.messages, True, on_tool_call, container=self.container_obj
        )

        await self.send_json({"event": "start_text"})
        self.messages, r_u = cast(
            tuple[list[OpenAIChatMessage], TokenUsage],
            await agent.get_response_no_tools(
                self.messages, False, on_chunk, on_finish
            ),
        )

        token_usage: TokenUsage = {
            "prompt_tokens": t_u["prompt_tokens"] + r_u["prompt_tokens"],
            "completion_tokens": t_u["completion_tokens"] + r_u["completion_tokens"],
            "total_tokens": t_u["total_tokens"] + r_u["total_tokens"],
        }
        await self._set_quota(
            self.user,
            user_text,
            self.messages[-1]["content"],
            self.container_obj,
            token_usage,
        )
        await self.send_json({"event": "memory_data", "memory": self.messages})
        await self._set_memory(self.user, self.container_obj, self.messages)

        quota, ai_uses_left_today = await self._get_quota(self.user_pk)
        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def disconnect(self, code: int):
        pass
