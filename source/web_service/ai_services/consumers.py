from __future__ import annotations
from django.apps import apps
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from internal_config.models import Config
from .utils import _get_openai_client
from .agents.agents import DevAgent


class AIConsumer(AsyncJsonWebsocketConsumer):
    """Thin WebSocket consumer: authorization, client/model init, streaming.

    All agent logic (tool loops, schemas, system prompt) lives in app.agents.*
    """

    @staticmethod
    @sync_to_async
    def _get_container(pk: int):
        container = apps.get_model("vm_manager", "Container")

        container_obj = None
        try:
            container_obj = container.objects.get(pk=pk)
        except container.DoesNotExist:
            return None

        return container_obj

    @staticmethod
    @sync_to_async
    def _user_owns_container(pk: int, user_pk: int) -> bool:
        user_mod = apps.get_model("auth", "User")

        user = user_mod.objects.get(pk=user_pk)
        if user.is_superuser:
            return True

        container = apps.get_model("vm_manager", "Container")
        return container.objects.filter(pk=pk, user_id=user_pk).exists()

    @staticmethod
    @sync_to_async
    def _get_quota(user_id: int):
        resource_quota_mod = apps.get_model("vm_manager", "ResourceQuota")
        try:
            quota = resource_quota_mod.objects.get(user_id=user_id)
            return quota, quota.ai_uses_left_today()
        except resource_quota_mod.DoesNotExist:
            return None, None

    @staticmethod
    @sync_to_async
    def _set_quota(user, query: str, response: str):
        ai_usage_log_model = apps.get_model("internal_config", "AIUsageLog")
        ai_usage_log_model.objects.create(user=user, query=query, response=response)

    @staticmethod
    @sync_to_async
    def _set_memory(user, container, memory_data):
        ai_memory = apps.get_model("internal_config", "AIMemory")
        memory, created = ai_memory.objects.get_or_create(
            user=user, container=container, defaults={"memory": memory_data}
        )

        if not created:
            memory.memory = memory_data
            memory.save()

    @staticmethod
    @sync_to_async
    def _get_memory(user, container):
        ai_memory = apps.get_model("internal_config", "AIMemory")
        memory = ai_memory.objects.filter(
            user=user,
            container=container,
        ).last()
        if not memory:
            return []
        return memory.memory

    @staticmethod
    @sync_to_async
    def _get_config_values():
        return Config.get_config_values(
            ["openai_api_key", "openai_api_url", "openai_model"]
        )

    @sync_to_async
    def _run_tool_loop(
        self,
    ):
        return self.agent.run_tool_loop(self.messages, self.container_obj)

    async def send_history(self, memory):
        for i, msg in enumerate(memory):
            if i == 0:
                continue

            if msg["content"].startswith(
                "Here some info that can help you with the user request:"
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

    def response_retry(self):
        for _ in range(2000):
            try:
                buff = ""
                for evt in self.client.chat.completions.create(
                    messages=self.messages,
                    model=self.openai_model,
                    stream=True,
                    tool_choice="none",
                    response_format={"type": "text"},
                ):
                    chunk = evt.choices[0].delta.content
                    if not chunk:
                        continue
                    buff += chunk
                    yield chunk

                if len(buff.strip()) != 0:
                    return
            except Exception as e:
                print(e)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []
        self.openai_model: str | None = None
        self.client = None
        self.agent: DevAgent | None = None
        self.user = None
        self.pk = -1
        self.container = None

    async def connect(self):
        self.user = self.scope["user"]

        if self.user.is_anonymous:
            await self.close(code=4401)
            return

        await self.accept()

        quota, ai_uses_left_today = await self._get_quota(self.user.pk)
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

        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        try:
            allowed = await self._user_owns_container(self.pk, self.user.pk)
            if not allowed:
                await self.close(code=4403)
                return
        except DatabaseError:
            await self.close(code=1011)
            return

        self.container_obj = await self._get_container(self.pk)
        if not self.container_obj:
            await self.close(code=4404)
            return

        cfg = await self._get_config_values()
        self.openai_model = cfg.get("openai_model") or "gpt-4o"
        self.client = _get_openai_client(cfg)
        self.agent = DevAgent(client=self.client, model=self.openai_model)

        self.messages = await self._get_memory(self.user, self.container_obj)
        if len(self.messages) == 0:
            self.messages = self.agent.bootstrap_messages()

        await self.send_history(self.messages)

        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def receive_json(self, content, **kwargs):
        user_text = content.get("text", "")[:1000]
        if not user_text.strip():
            return

        if not self.agent:
            print("[AGENT]: Not agent found")
            return

        quota, ai_uses_left_today = await self._get_quota(self.user.pk)
        if quota is None or ai_uses_left_today is None or ai_uses_left_today <= 0:
            await self.send_json({"event": "start_text"})
            await self.send_json(
                {
                    "event": "text",
                    "content": "You have no available quota for today, try it tomorrow...",
                }
            )
            await self.send_json({"event": "finish_text"})
            await self.close(code=4401)
            return

        # Process LLM
        self.messages.append({"role": "user", "content": user_text})

        await self.send_json({"event": "start_text"})
        self.messages = await self._run_tool_loop()

        buffer = ""
        for chunk in self.response_retry():
            if not chunk:
                continue
            buffer += chunk
            await self.send_json({"event": "text", "content": chunk})

        self.messages.append({"role": "assistant", "content": buffer})

        await self.send_json({"event": "finish_text"})
        await self.send_json({"event": "memory_data", "memory": self.messages})

        await self._set_memory(self.user, self.container_obj, self.messages)

        # Set Quota
        await self._set_quota(self.user, user_text, buffer)
        quota, ai_uses_left_today = await self._get_quota(self.user.pk)

        await self.send_json(
            {"event": "connected", "ai_uses_left_today": ai_uses_left_today}
        )

    async def disconnect(self, code):
        pass
