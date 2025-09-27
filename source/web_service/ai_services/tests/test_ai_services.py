import asyncio
import json
import types
import pytest
import os

from django.contrib.auth import get_user_model
from django.urls import re_path
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter

from web_service.vm_manager.test_utils import (
    create_user,
    create_quota,
    create_node,
    create_container,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


class FakeStreamingEvent:
    def __init__(self, content: str):
        # Mimic OpenAI streaming delta structure
        delta = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(delta=delta)
        self.choices = [choice]


class FakeChatCompletions:
    def __init__(self, stream_chunks=None, static_message=None, tool_response=None):
        self._stream_chunks = stream_chunks or []
        self._static_message = static_message or "ok"
        self._tool_response = tool_response  # optionally return a structured tool call

    def create(self, *, messages, model, stream=False, **kwargs):
        if stream:
            # Streaming path: return an iterator of events (avoid making this a generator function)
            return (FakeStreamingEvent(ch) for ch in self._stream_chunks)
        # Non-streaming path used by DevAgent.get_response
        # Must return an object with choices[0].message.content and choices[0].finish_reason
        if self._tool_response:
            return self._tool_response
        msg = types.SimpleNamespace(content=self._static_message, tool_calls=None)
        choice = types.SimpleNamespace(message=msg, finish_reason="stop")
        return types.SimpleNamespace(choices=[choice])


class FakeOpenAI:
    def __init__(self, stream_chunks=None, static_message=None, tool_response=None):
        self.chat = types.SimpleNamespace(
            completions=FakeChatCompletions(
                stream_chunks=stream_chunks,
                static_message=static_message,
                tool_response=tool_response,
            )
        )


class FakeAgent:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    @staticmethod
    def bootstrap_messages():
        return [{"role": "system", "content": "system-prompt"}]

    def run_tool_loop(self, messages, container, max_rounds: int = 8):
        # Return an async generator as the real code expects
        async def _gen():
            # Immediately finish without invoking any tools
            yield True, messages

        return _gen()


def build_auth_app(user, route):
    # Minimal auth middleware to inject the test user
    class FakeAuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["user"] = user
            return await self.app(scope, receive, send)

    return FakeAuthMiddleware(URLRouter(route))


async def drain_until(comm: WebsocketCommunicator, predicate, timeout=2.0):
    """
    Drain incoming events until predicate(event_dict) returns True
    or timeout expires. Returns the matched event.
    """
    end = asyncio.get_event_loop().time() + timeout
    last = None
    while asyncio.get_event_loop().time() < end:
        try:
            data = await asyncio.wait_for(comm.receive_json_from(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        last = data
        if predicate(data):
            return data
    return last


def test_ai_consumer_connect_and_receive_flow(monkeypatch):
    # Arrange DB objects outside the event loop to avoid sync ORM from async context
    user = create_user(username="aiws_bob", password="secret")
    create_quota(user=user, ai_use_per_day=5)
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-conn-1")

    # Patch AI consumer deps
    import web_service.ai_services.ai_consumers as ai_consumers

    # Ensure config returns a fake API key/model
    monkeypatch.setattr(
        ai_consumers.Config,
        "get_config_values",
        staticmethod(
            lambda keys: {
                "openai_api_key": "test-key",
                "openai_model": "gpt-x",
                "openai_api_url": "http://fake",
            }
        ),
    )

    # Fake OpenAI client that will stream two chunks
    fake_client = FakeOpenAI(
        stream_chunks=["Hello", " world"], static_message="irrelevant"
    )
    monkeypatch.setattr(ai_consumers, "get_openai_client", lambda cfg: fake_client)

    # Use a lightweight fake agent to skip tool-calls complexity
    monkeypatch.setattr(ai_consumers, "DevAgent", FakeAgent)

    # Patch AIConsumer DB accessors to avoid cross-thread SQLite access during the WS test
    calls = {"uses": 5}

    async def fake_get_quota(user_id):
        # return dummy quota object and remaining uses
        return object(), calls["uses"]

    async def fake_set_quota(user, query, response, container):
        # decrement uses to simulate logging consumption
        calls["uses"] = max(calls["uses"] - 1, 0)

    async def fake_set_memory(user, container, memory_data):
        return None

    async def fake_get_memory(user, container):
        # no prior memory
        return []

    async def fake_get_container_simple(pk):
        # return the pre-created container directly
        return container

    async def fake_user_owns_container(pk, user_pk):
        return True

    async def fake_get_config_values():
        return {
            "openai_api_key": "test-key",
            "openai_model": "gpt-x",
            "openai_api_url": "http://fake",
        }

    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_quota", staticmethod(fake_get_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_set_quota", staticmethod(fake_set_quota)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_set_memory", staticmethod(fake_set_memory)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer, "_get_memory", staticmethod(fake_get_memory)
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_get_container_simple",
        staticmethod(fake_get_container_simple),
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_user_owns_container",
        staticmethod(fake_user_owns_container),
    )
    monkeypatch.setattr(
        ai_consumers.AIConsumer,
        "_get_config_values",
        staticmethod(fake_get_config_values),
    )

    # Build ASGI app with URLRouter so url_route.kwargs are available
    route = [re_path(r"^ws/ai/(?P<pk>\d+)/$", ai_consumers.AIConsumer.as_asgi())]
    app = build_auth_app(user, route)

    async def _main():
        # Act: connect
        communicator = WebsocketCommunicator(app, f"/ws/ai/{container.pk}/")
        connected, _ = await communicator.connect()
        assert connected is True

        # Expect final connected event after initial history (none to render)
        evt = await drain_until(communicator, lambda e: e.get("event") == "connected")
        assert evt and evt.get("event") == "connected"
        assert isinstance(evt.get("ai_uses_left_today"), int)

        # Send a normal user message
        await communicator.send_json_to({"text": "hola"})

        # It should first emit start_text + "..." placeholder
        start_evt = await drain_until(
            communicator, lambda e: e.get("event") == "start_text"
        )
        assert start_evt and start_evt.get("event") == "start_text"

        placeholder = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and e.get("content") == "...",
        )
        assert placeholder and placeholder.get("content") == "..."

        # Then we should receive the streamed chunks from FakeOpenAI
        chunk1 = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and "Hello" in e.get("content", ""),
        )
        assert chunk1 and "Hello" in (chunk1.get("content") or "")

        chunk2 = await drain_until(
            communicator,
            lambda e: e.get("event") == "text" and "world" in e.get("content", ""),
        )
        assert chunk2 and "world" in (chunk2.get("content") or "")

        # The assistant should finish, send memory and updated quota
        finish_evt = await drain_until(
            communicator, lambda e: e.get("event") == "finish_text"
        )
        assert finish_evt and finish_evt.get("event") == "finish_text"

        memory_evt = await drain_until(
            communicator, lambda e: e.get("event") == "memory_data"
        )
        assert memory_evt and memory_evt.get("event") == "memory_data"
        assert isinstance(memory_evt.get("memory"), list)
        assert any(m.get("role") == "assistant" for m in memory_evt["memory"])

        connected_evt2 = await drain_until(
            communicator, lambda e: e.get("event") == "connected"
        )
        assert connected_evt2 and connected_evt2.get("event") == "connected"
        assert connected_evt2["ai_uses_left_today"] <= evt["ai_uses_left_today"]

        await communicator.disconnect()

    asyncio.run(_main())


def test_utils_get_openai_client_uses_api_key_and_url(monkeypatch):
    # We patch the OpenAI class in utils to capture initialization args
    import web_service.ai_services.utils as utils

    captured = {}

    class DummyOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(utils, "OpenAI", DummyOpenAI)

    # Act
    client = utils.get_openai_client(
        {"openai_api_key": "abc123", "openai_api_url": "http://localhost:9999/v1"}
    )

    # Assert: the function returns our DummyOpenAI instance with provided values
    assert isinstance(client, DummyOpenAI)
    assert captured["api_key"] == "abc123"
    assert captured["base_url"] == "http://localhost:9999/v1"


def test_create_full_project_uses_openai_and_vm_service(monkeypatch):
    # Arrange DB objects
    user = create_user(username="carol_ai_proj")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-proj-1")

    # Patch tools dependencies
    import web_service.ai_services.agents.tools as tools_mod
    from web_service.ai_services.agents.tools import DedupPolicy

    # Fake OpenAI non-streaming completion returning a YAML-like body
    generated_body = """Some explanation
---HERE-YAML--
project: demo
files: []
"""
    fake_openai = FakeOpenAI(static_message=generated_body)
    import web_service.ai_services.utils as utils

    monkeypatch.setattr(utils, "get_openai_client", lambda cfg: fake_openai)

    # Config fetch: patch actual app model via importlib to avoid app_label issues
    import importlib

    ic_models = importlib.import_module("internal_config.models")
    monkeypatch.setattr(
        ic_models.Config,
        "get_config_values",
        staticmethod(
            lambda keys: {
                "openai_api_key": "k",
                "openai_model": "m",
                "openai_api_url": "u",
            }
        ),
    )

    # Fake VM service to capture calls
    calls = {}

    class FakeVMService:
        def upload_files(self, vm_id, payload):
            calls["upload"] = {"vm_id": vm_id, "payload": payload}
            return {"ok": True}

        def execute_sh(self, vm_id, cmd):
            calls["exec"] = {"vm_id": vm_id, "cmd": cmd}
            return {"ok": True}

        def list_dirs(self, vm_id, path):
            calls["list_dir"] = {"vm_id": vm_id, "path": path}
            return [{"path": "/app/readme.txt", "is_dir": False}]

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    # Act
    resp = tools_mod.create_full_project(
        DedupPolicy(), container, full_description="Build a demo app"
    )

    # Assert: service calls performed
    assert "upload" in calls
    assert "exec" in calls
    assert calls["exec"]["cmd"] == "cd /app && python3 build_from_gencode.py"

    # The response should contain finished and workspace
    assert isinstance(resp, dict)
    assert resp.get("finished") is True
    assert "workspace" in resp
    assert resp["workspace"]["path"] == "/app"
    assert isinstance(resp["workspace"]["entries"], list)


def test_tools_read_workspace_lists_dir(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod

    user = create_user(username="dan_ai_tools")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-rw-1")

    class FakeVMService:
        def list_dirs(self, vm_id, path):
            return [{"name": "a.txt"}]

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    out = tools_mod.read_workspace(None, container, subdir="src")
    assert out["path"] == "/app/src"
    assert isinstance(out["entries"], list)


def test_tools_create_file_uploads_and_dedups(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from web_service.ai_services.agents.tools import DedupPolicy

    user = create_user(username="erin_ai_tools")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-cf-1")

    calls = {"uploads": 0}

    class FakeVMService:
        def upload_files(self, vm_id, payload):
            calls["uploads"] += 1
            return {"ok": True}

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    DedupPolicy.logs = {}
    d = DedupPolicy()

    resp1 = tools_mod.create_file(d, container, path="a.txt", content="Hello")
    assert resp1.get("finished") is True
    assert calls["uploads"] == 1

    resp2 = tools_mod.create_file(d, container, path="a.txt", content="Hello again")
    assert resp2.get("dedup") is True
    assert calls["uploads"] == 1


def test_tools_read_file_fetches_content(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from web_service.ai_services.agents.tools import DedupPolicy

    user = create_user(username="frank_ai_tools")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-rf-1")

    class FakeVMService:
        def read_file(self, vm_id, path):
            return {"path": path, "text": "hi"}

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    out = tools_mod.read_file(DedupPolicy(), container, path="README.md")
    assert out["text"] == "hi"
    assert out.get("finished") is True


def test_tools_exec_command_runs(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from web_service.ai_services.agents.tools import DedupPolicy

    user = create_user(username="gina_ai_tools")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-ex-1")

    class FakeVMService:
        def execute_sh(self, vm_id, cmd):
            return {"ok": True, "cmd": cmd}

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    out = tools_mod.exec_command(DedupPolicy(), container, command="echo ok")
    assert out.get("finished") is True
    assert out.get("cmd") == "echo ok"


def test_tools_search_calls_service_and_audits(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from internal_config.models import AuditLog as ALog

    user = create_user(username="harry_ai_search")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-search-1")

    captured = {}

    class FakeVMService:
        def search(self, vm_id, req):
            captured["vm_id"] = vm_id
            captured["pattern"] = getattr(req, "pattern", None)
            captured["root"] = getattr(req, "root", None)
            return [{"path": "/app/a.txt"}]

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    out = tools_mod.search(None, container, pattern="README", root="/app")
    assert out.get("finished") is True
    assert isinstance(out.get("response"), list)
    assert captured["vm_id"] == str(container.container_id)
    assert captured["pattern"] == "README"
    assert captured["root"] == "/app"

    log = ALog.objects.filter(action="agent_tool.search").first()
    assert log is not None
    assert log.metadata.get("pattern") == "README"
    assert log.metadata.get("root") == "/app"


def test_tools_search_on_internet_returns_results_and_audits(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from internal_config.models import AuditLog as ALog

    user = create_user(username="ivy_ai_web")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-web-1")

    class FakeDDGS:
        def text(self, q, max_results=5, timeout=5):
            return [{"title": "r1"}, {"title": "r2"}]

    import sys

    fake_ddgs = types.ModuleType("ddgs")
    fake_ddgs.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs)

    out = tools_mod.search_on_internet(None, container, search_query="python")
    assert out.get("finished") is True
    assert isinstance(out.get("response"), list)
    assert len(out["response"]) == 2

    log = ALog.objects.filter(action="agent_tool.search_on_internet").first()
    assert log is not None
    assert log.metadata.get("query") == "python"


def test_tools_read_from_internet_success_audits(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from internal_config.models import AuditLog as ALog

    user = create_user(username="jack_ai_read_web")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-web-2")

    class FakeArticleSuccess:
        def __init__(self, url: str):
            self._url = url
            self.title = "Hello"
            self.text = "World"

        def download(self):
            return None

        def parse(self):
            return None

    import sys

    fake_news = types.ModuleType("newspaper")
    fake_news.Article = FakeArticleSuccess
    monkeypatch.setitem(sys.modules, "newspaper", fake_news)

    out = tools_mod.read_from_internet(None, container, url="http://example.com")
    assert out.get("finished") is True
    assert out.get("title") == "Hello"
    assert out.get("text") == "World"

    log = ALog.objects.filter(action="agent_tool.read_from_internet").first()
    assert log is not None
    assert log.success is True
    assert log.metadata.get("url") == "http://example.com"
    assert log.metadata.get("title") == "Hello"
    assert "error" not in log.metadata


def test_tools_read_from_internet_error_audits(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from internal_config.models import AuditLog as ALog

    user = create_user(username="kate_ai_read_web")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-web-3")

    class FakeArticleError:
        def __init__(self, url: str):
            pass

        def download(self):
            raise RuntimeError("network down")

        def parse(self):
            return None

    import sys

    fake_news = types.ModuleType("newspaper")
    fake_news.Article = FakeArticleError
    monkeypatch.setitem(sys.modules, "newspaper", fake_news)

    out = tools_mod.read_from_internet(None, container, url="http://bad")
    assert out.get("finished") is True
    assert "error" in out

    log = ALog.objects.filter(action="agent_tool.read_from_internet").first()
    assert log is not None
    assert log.success is False
    assert log.metadata.get("url") == "http://bad"
    assert "error" in log.metadata


def test_tools_exec_command_risk_level_audited(monkeypatch):
    import web_service.ai_services.agents.tools as tools_mod
    from web_service.ai_services.agents.tools import DedupPolicy
    from internal_config.models import AuditLog as ALog

    user = create_user(username="leo_ai_risk")
    node = create_node()
    container = create_container(user=user, node=node, container_id="vm-risk-2")

    class FakeVMService:
        def execute_sh(self, vm_id, cmd):
            return {"ok": True, "cmd": cmd}

    monkeypatch.setattr(tools_mod, "_get_service", lambda obj: FakeVMService())

    tools_mod.exec_command(DedupPolicy(), container, command="docker push repo/image")
    log = ALog.objects.filter(action="agent_tool.exec_command").first()
    assert log is not None
    assert log.metadata.get("risk_level") == "HIGH"
    assert log.metadata.get("command") == "docker push repo/image"
