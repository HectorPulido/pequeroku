import asyncio
import types
from typing import Any

import pytest


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


@pytest.mark.django_db
def test_read_workspace_order(monkeypatch):
    # Arrange
    import ai_services.ai_engineer.tools as tools_mod

    call_order: list[tuple[str, Any]] = []

    class FakeService:
        def list_dirs(self, vm_id, paths):
            call_order.append(("list_dirs", vm_id, paths))
            return [{"name": "file.txt"}]

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    container = _ns(container_id="vm-1", node=None)

    # Act
    async def _run():
        out = await tools_mod.read_workspace(container, subdir="src")
        return out

    out = asyncio.run(_run())

    # Assert
    assert isinstance(out, dict)
    assert out["finished"] is True
    assert out["path"] == "/app/src"
    assert call_order[0][0] == "get_service"
    assert call_order[1][0] == "list_dirs"
    assert call_order[2][0] == "audit"


@pytest.mark.django_db
def test_create_file_order_and_dedup(monkeypatch):
    # Arrange
    import ai_services.ai_engineer.tools as tools_mod
    from ai_services.agents import DedupPolicy

    call_order: list[tuple[str, Any]] = []

    class FakeService:
        def upload_files(self, vm_id, payload):
            call_order.append(("upload_files", vm_id, payload))
            return {"ok": True}

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    container = _ns(container_id="vm-1", node=None)
    d = DedupPolicy()

    # Act 1: first call (not dedup) -> get_service -> upload_files -> audit
    async def _run_first():
        return await tools_mod.create_file(d, container, path="a.txt", content="hello")

    out1 = asyncio.run(_run_first())

    # Assert first call
    assert isinstance(out1, dict) and out1["finished"] is True
    assert [entry[0] for entry in call_order] == [
        "get_service",
        "upload_files",
        "audit",
    ]

    # Act 2: second call (dedup) -> audit only (no get_service/upload_files)
    call_order.clear()

    async def _run_second():
        return await tools_mod.create_file(
            d, container, path="a.txt", content="hello again"
        )

    out2 = asyncio.run(_run_second())

    # Assert second call
    assert out2.get("dedup") is True
    assert [entry[0] for entry in call_order] == ["audit"]


@pytest.mark.django_db
def test_read_file_order(monkeypatch):
    # Arrange
    import ai_services.ai_engineer.tools as tools_mod
    from ai_services.agents import DedupPolicy

    call_order: list[tuple[str, Any]] = []

    class FakeService:
        def read_file(self, vm_id, path):
            call_order.append(("read_file", vm_id, path))
            return {"path": path, "text": "hi"}

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    container = _ns(container_id="vm-1", node=None)

    # Act
    async def _run():
        return await tools_mod.read_file(container, path="README.md")

    out = asyncio.run(_run())

    # Assert
    assert out["finished"] is True
    assert [entry[0] for entry in call_order] == ["get_service", "read_file", "audit"]


@pytest.mark.django_db
def test_exec_command_order(monkeypatch):
    # Arrange
    import ai_services.ai_engineer.tools as tools_mod
    from ai_services.agents import DedupPolicy

    call_order: list[tuple[str, Any]] = []

    class FakeService:
        def execute_sh(self, vm_id, cmd):
            call_order.append(("execute_sh", vm_id, cmd))
            return {"ok": True, "cmd": cmd}

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    container = _ns(container_id="vm-1", node=None)

    # Act
    async def _run():
        return await tools_mod.exec_command(container, command="echo ok")

    out = asyncio.run(_run())

    # Assert
    assert out["finished"] is True
    assert out["cmd"] == "echo ok"
    assert [entry[0] for entry in call_order] == ["get_service", "execute_sh", "audit"]


@pytest.mark.django_db
def test_search_order(monkeypatch):
    # Arrange
    import ai_services.ai_engineer.tools as tools_mod
    from ai_services.agents import DedupPolicy

    call_order: list[tuple[str, Any]] = []

    class FakeService:
        def search(self, vm_id, req):
            call_order.append(("search", vm_id, req))
            return [{"path": "/app/a.txt"}]

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    container = _ns(container_id="vm-1", node=None)

    # Act
    async def _run():
        return await tools_mod.search(container, pattern="README", root="/app")

    out = asyncio.run(_run())

    # Assert
    assert out["finished"] is True
    names = [entry[0] for entry in call_order]
    assert names == ["get_service", "search", "audit"]
    # Also validate audit metadata includes our pattern and root
    audit_kwargs = [entry[1] for entry in call_order if entry[0] == "audit"][0]
    assert audit_kwargs["metadata"]["pattern"] == "README"
    assert audit_kwargs["metadata"]["root"] == "/app"


@pytest.mark.django_db
def test_create_full_project_order(monkeypatch):
    # Arrange
    import builtins
    import io
    from django.conf import settings
    import ai_services.ai_engineer.tools as tools_mod
    from ai_services.agents import DedupPolicy

    call_order: list[tuple[str, Any]] = []

    # Patch Config.get_config_values via import path
    def fake_get_config_values(keys):
        call_order.append(("config", tuple(keys)))
        return {
            "openai_api_key": "k",
            "openai_api_url": "http://fake/v1",
            "openai_model": "m",
        }

    monkeypatch.setattr(
        "internal_config.models.Config.get_config_values",
        staticmethod(fake_get_config_values),
        raising=False,
    )

    # Patch OpenAI client factory
    class FakeOpenAI:
        def __init__(self):
            self.chat = _ns(
                completions=_ns(
                    create=lambda **kwargs: _ns(
                        choices=[
                            _ns(
                                message=_ns(
                                    content="---HERE-YAML--\nproject: demo\nfiles: []\n"
                                )
                            )
                        ]
                    )
                )
            )

    def fake_get_openai_client(cfg):
        call_order.append(("openai_client", cfg.copy()))
        return FakeOpenAI()

    monkeypatch.setattr(
        "ai_services.utils.get_openai_client",
        fake_get_openai_client,
        raising=False,
    )

    # Patch settings.BASE_DIR to avoid relying on repo structure
    monkeypatch.setattr(settings, "BASE_DIR", "/tmp/fake-base", raising=False)

    # Patch open() used to read build_from_gencode.py
    def fake_open(file, mode="r", encoding=None):
        call_order.append(("open", file))

        # Return a context manager that yields a StringIO
        class Ctx:
            def __enter__(self_nonlocal):
                return io.StringIO("# generated script")

            def __exit__(self_nonlocal, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(builtins, "open", fake_open, raising=False)

    # Patch VM service and audit
    class FakeService:
        def upload_files(self, vm_id, payload):
            call_order.append(("upload_files", vm_id, payload))
            return {"ok": True}

        def execute_sh(self, vm_id, cmd):
            call_order.append(("execute_sh", vm_id, cmd))
            return {"ok": True}

    def fake_get_service(container):
        call_order.append(("get_service", container.container_id))
        return FakeService()

    def fake_audit_agent_tool(**kwargs):
        call_order.append(("audit", kwargs))

    monkeypatch.setattr(tools_mod, "_get_service", fake_get_service)
    monkeypatch.setattr(tools_mod, "audit_agent_tool", fake_audit_agent_tool)

    # Patch read_workspace to return a dict synchronously (tools.create_full_project calls it without await)
    def fake_read_workspace(_c, _):
        call_order.append(("read_workspace", _c.container_id))
        return {"path": "/app", "entries": []}

    monkeypatch.setattr(tools_mod, "read_workspace", fake_read_workspace, raising=False)

    container = _ns(container_id="vm-1", node=None)
    d = DedupPolicy()

    # Act
    async def _run():
        return await tools_mod.create_full_project(
            d, container, full_description="Build a demo app"
        )

    out = asyncio.run(_run())

    # Assert order
    names = [c[0] for c in call_order]
    # Expect: read config -> get openai client -> openai completion -> get_service -> open file -> upload -> execute -> read_workspace -> audit
    assert names == [
        "config",
        "openai_client",
        # openai.chat.completions.create isn't logged directly; but we can check by result content
        "get_service",
        "open",
        "upload_files",
        "execute_sh",
        "read_workspace",
        "audit",
    ]

    assert isinstance(out, dict)
    assert out["finished"] is True
    assert out["workspace"]["path"] == "/app"
    # Validate that the OpenAI completion result was processed (gencode written and then execute_sh called)
    assert any(n == "upload_files" for n in names)
    assert any(n == "execute_sh" for n in names)
