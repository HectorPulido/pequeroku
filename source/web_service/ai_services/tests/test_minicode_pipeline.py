"""Tests for the Django bridge (frontends/pipeline.py) without network or DB.

``Agent``, ``LLM`` and the DB config read are mocked, so we exercise the real
sync<->async bridge: the worker thread runs the (fake) agent generator and each
event is marshalled to the async callbacks on the loop.
"""

from __future__ import annotations

from types import SimpleNamespace

import ai_services.minicode.frontends.pipeline as pipeline
from ai_services.minicode.session import Session


def _fake_config():
    return {"openai_api_key": "k", "openai_api_url": "http://x", "openai_model": "m"}


class _FakeLLM:
    def __init__(self, config):
        self.config = config


class _FakeAgent:
    def __init__(self, config, llm, session=None, **kwargs):
        self.session = session

    def run(self):
        from ai_services.minicode.events import (
            AssistantTextStart,
            AssistantTextDelta,
            AssistantTextEnd,
            ToolCallStarted,
            Usage,
        )

        yield AssistantTextStart(depth=0)
        yield AssistantTextDelta(text="Hi", depth=0)
        yield ToolCallStarted(name="bash", args={"command": "ls"}, depth=0)
        yield Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3, depth=0)
        yield AssistantTextDelta(text=" there", depth=0)
        yield AssistantTextEnd(depth=0)
        self.session.add_assistant("Hi there", [])
        return "Hi there"


async def test_run_pipeline_streams_events_and_returns_messages(monkeypatch):
    monkeypatch.setattr(pipeline, "_read_ai_config", _fake_config)
    monkeypatch.setattr(pipeline, "LLM", _FakeLLM)
    monkeypatch.setattr(pipeline, "Agent", _FakeAgent)

    chunks: list[str] = []
    starts: list[bool] = []
    finishes: list[str] = []
    tools: list[tuple] = []

    async def on_chunk(t):
        chunks.append(t)

    async def on_tool_call(name, **kw):
        tools.append((name, kw.get("command")))

    async def on_start():
        starts.append(True)

    async def on_finish(text):
        finishes.append(text)

    container = SimpleNamespace(id="vm-1", container_id="vm-1", node=object())

    messages, usage = await pipeline.run_pipeline(
        query="do it",
        messages=[],
        container_obj=container,
        on_chunk=on_chunk,
        on_tool_call=on_tool_call,
        on_start_chunking=on_start,
        on_finish_chunking=on_finish,
    )

    assert chunks == ["Hi", " there"]
    assert ("bash", "ls") in tools
    assert starts and finishes == ["Hi there"]
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
        1,
        2,
        3,
    )
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "Hi there"
    assert any(m["role"] == "user" and m["content"] == "do it" for m in messages)


async def test_run_pipeline_reports_agent_error_as_text(monkeypatch):
    monkeypatch.setattr(pipeline, "_read_ai_config", _fake_config)
    monkeypatch.setattr(pipeline, "LLM", _FakeLLM)

    class _BoomAgent:
        def __init__(self, *a, **k):
            pass

        def run(self):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(pipeline, "Agent", _BoomAgent)

    errs: list[str] = []

    async def noop(*a, **k):
        pass

    async def on_finish(text):
        errs.append(text)

    container = SimpleNamespace(id="vm-1", container_id="vm-1", node=object())
    messages, usage = await pipeline.run_pipeline(
        query="q",
        messages=[],
        container_obj=container,
        on_chunk=noop,
        on_tool_call=noop,
        on_start_chunking=noop,
        on_finish_chunking=on_finish,
    )
    # the turn never crashes: the error is surfaced as the assistant message
    assert messages[-1]["role"] == "assistant"
    assert "kaboom" in messages[-1]["content"]
    assert errs and "kaboom" in errs[0]


class _RichAgent:
    """Yields one of every internal event, to exercise on_event forwarding."""

    def __init__(self, config, llm, session=None, **kwargs):
        self.session = session

    def run(self):
        from ai_services.minicode.events import (
            ToolCallStarted,
            ToolResult,
            TodosUpdated,
            SubagentStarted,
            SubagentFinished,
            Info,
            Error,
            Usage,
        )

        yield ToolCallStarted(name="bash", args={"command": "ls"}, depth=0)
        yield ToolResult(name="bash", output="file1\nfile2", depth=0)
        yield TodosUpdated(todos=[{"content": "do x", "status": "pending"}], depth=0)
        yield SubagentStarted(agent_type="explore", prompt="find x", depth=0)
        yield SubagentFinished(agent_type="explore", depth=1)
        yield Info(message="just so you know", depth=0)
        yield Error(message="non-fatal", depth=0)
        yield Usage(prompt_tokens=5, completion_tokens=6, total_tokens=11, depth=0)
        self.session.add_assistant("done", [])
        return "done"


async def test_run_pipeline_forwards_internal_events(monkeypatch):
    monkeypatch.setattr(pipeline, "_read_ai_config", _fake_config)
    monkeypatch.setattr(pipeline, "LLM", _FakeLLM)
    monkeypatch.setattr(pipeline, "Agent", _RichAgent)

    events: list[dict] = []

    async def on_event(payload):
        events.append(payload)

    async def noop(*a, **k):
        pass

    container = SimpleNamespace(id="vm-1", container_id="vm-1", node=object())
    _messages, usage = await pipeline.run_pipeline(
        query="q",
        messages=[],
        container_obj=container,
        on_chunk=noop,
        on_tool_call=noop,
        on_start_chunking=noop,
        on_finish_chunking=noop,
        on_event=on_event,
    )

    by_type = {e["type"]: e for e in events}
    assert by_type["tool_call"]["name"] == "bash"
    assert by_type["tool_call"]["args"] == {"command": "ls"}
    assert by_type["tool_call"]["command"] == "ls"
    assert by_type["tool_result"]["output"] == "file1\nfile2"
    assert by_type["todos"]["todos"][0]["content"] == "do x"
    assert by_type["subagent_started"]["agent_type"] == "explore"
    assert by_type["subagent_finished"]["agent_type"] == "explore"
    assert by_type["info"]["message"] == "just so you know"
    assert by_type["error"]["message"] == "non-fatal"
    assert by_type["usage"]["total_tokens"] == 11
    # usage is also accumulated into the returned total
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
        5,
        6,
        11,
    )


def test_synth_command_variants():
    s = pipeline._synth_command
    assert s("bash", {"command": "ls -la"}) == "ls -la"
    assert s("process", {"action": "status", "job_id": "j1"}) == "process status j1"
    assert s("read", {"filePath": "a.py"}) == "read a.py"
    assert s("grep", {"pattern": "TODO"}) == "grep TODO"
    assert s("read_from_internet", {"url": "http://x"}) == "read_from_internet http://x"
    assert s("task", {"subagent_type": "explore", "description": "find x"}).startswith(
        "task:explore"
    )
    assert s("todowrite", {"todos": [1, 2, 3]}) == "todowrite (3 items)"
    assert s("mystery", {}) == "mystery"


def test_final_messages_keeps_clean_assistant_else_appends_fallback():
    s = Session()
    s.messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "answer"},
    ]
    assert pipeline._final_messages(s, "fb")[-1]["content"] == "answer"

    s2 = Session()
    s2.messages = [{"role": "user", "content": "q"}]
    assert pipeline._final_messages(s2, "fallback")[-1] == {
        "role": "assistant",
        "content": "fallback",
    }


def test_agent_info_model_reads_config_and_falls_back(monkeypatch):
    monkeypatch.setattr(pipeline, "_read_ai_config", lambda: {"openai_model": "gpt-x"})
    assert pipeline.agent.model == "gpt-x"

    def boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(pipeline, "_read_ai_config", boom)
    assert pipeline.agent.model == pipeline._DEFAULT_MODEL
