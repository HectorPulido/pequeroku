import json
import types
import pytest
import asyncio

from ai_services.agents import (
    Agent,
    AgentParameter,
    AgentTool,
    OpenAIMessage,
    DedupPolicy,
)


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


class FakeStreamingEvent:
    def __init__(self, content: str, prompt_tokens=0, completion_tokens=1):
        # Mimic OpenAI streaming delta structure with usage available on the event
        self.choices = [_ns(delta=_ns(content=content))]
        self.usage = _ns(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )


class FakeChatCompletions:
    def __init__(
        self,
        *,
        tool_name: str = "echo_tool",
        tool_args: dict | None = None,
        tool_usage=(1, 2),  # (prompt, completion)
        summary_text: str = "Summary: done",
        summary_usage=(2, 3),
        stream_chunks: list[str] | None = None,
        stream_usage_per_chunk=(0, 1),
    ):
        self.tool_name = tool_name
        self.tool_args = tool_args or {"a": 1}
        self.tool_usage = tool_usage
        self.summary_text = summary_text
        self.summary_usage = summary_usage
        self.stream_chunks = stream_chunks or []
        self.stream_usage_per_chunk = stream_usage_per_chunk

    def create(self, *, messages, model, stream=False, tools=None, **kwargs):
        if stream:
            # Streaming path: return an iterator of events
            p, c = self.stream_usage_per_chunk
            return (
                FakeStreamingEvent(ch, prompt_tokens=p, completion_tokens=c)
                for ch in self.stream_chunks
            )

        if tools is not None:
            # This is the "tools" turn
            msg = _ns(
                content="Plan: 1 step",
                tool_calls=[
                    _ns(
                        id="call_1",
                        type="function",
                        function=_ns(
                            name=self.tool_name,
                            arguments=json.dumps(self.tool_args, ensure_ascii=False),
                        ),
                    )
                ],
            )
            choice = _ns(message=msg, finish_reason="stop")
            prompt, completion = self.tool_usage
            usage = _ns(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
            )
            return _ns(choices=[choice], usage=usage)

        # Summary turn (no tools argument)
        msg = _ns(content=self.summary_text, tool_calls=None)
        choice = _ns(message=msg, finish_reason="stop")
        prompt, completion = self.summary_usage
        usage = _ns(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )
        return _ns(choices=[choice], usage=usage)


class FakeOpenAI:
    def __init__(self, **kwargs):
        self.chat = _ns(completions=FakeChatCompletions(**kwargs))


def test_openai_message_builders_and_types():
    a = OpenAIMessage.get_assistant_message("hi")
    u = OpenAIMessage.get_user_message("hey")
    s = OpenAIMessage.get_system_message("sys")

    assert a["role"] == "assistant" and a["content"] == "hi"
    assert u["role"] == "user" and u["content"] == "hey"
    assert s["role"] == "system" and s["content"] == "sys"

    call = OpenAIMessage.get_tool_calling_message("id1", "t1", {"x": 1})
    assert call["role"] == "assistant"
    assert call["tool_calls"][0]["function"]["name"] == "t1"
    assert json.loads(call["tool_calls"][0]["function"]["arguments"]) == {"x": 1}

    resp = OpenAIMessage.get_tool_response_message("id1", "t1", {"ok": True})
    assert resp["role"] == "tool"
    assert resp["tool_call_id"] == "id1"
    assert resp["name"] == "t1"
    assert json.loads(resp["content"]) == {"ok": True}


def test_agent_parameter_and_tool_generation_and_render():
    p1 = AgentParameter(name="path", description="File path", type="string")
    p2 = AgentParameter(name="content", description="File content", type="string")

    # Parameter dict generation
    n1, o1 = p1.generate_parameter_dict()
    assert n1 == "path"
    assert o1["type"] == "string" and o1["description"] == "File path"

    # Render parameters
    rendered = AgentParameter.render_parameters([p1, p2])
    assert "path: string -> File path" in rendered
    assert "content: string -> File content" in rendered

    # Tool generation
    def dummy(**kwargs):
        return {"ok": True}

    tool = AgentTool(
        name="create_file",
        description="Create file",
        parameters=[p1, p2],
        agent_call=dummy,
    )

    tdict = tool.generate_tool_dict()
    assert tdict["type"] == "function"
    assert tdict["function"]["name"] == "create_file"
    assert tdict["function"]["parameters"]["required"] == ["path", "content"]
    assert tdict["function"]["strict"] is True
    assert tdict["function"]["parameters"]["additionalProperties"] is False

    # Render agents
    tools_str = AgentTool.render_agents([tool])
    assert "tool create_file>" in tools_str
    assert "path: string" in tools_str


def test_agent_set_first_message_and_planner_prompt_integration():
    client = FakeOpenAI()
    params = []
    tools = []
    agent = Agent(
        client=client,
        model="gpt-x",
        tools=tools,
        tool_prompt="TOOLS: {tools}",
        no_tools_prompt="NO TOOLS HERE {tools}",
        max_rounds=2,
    )

    # Empty -> system inserted
    msgs = []
    out = agent._set_first_message(msgs, "SYS-{time}")
    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith("SYS-")

    # Existing user -> system prepended
    msgs = [OpenAIMessage.get_user_message("u1")]
    out = agent._set_first_message(msgs, "SYS2-{time}")
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"

    # Existing system -> replaced
    msgs = [
        OpenAIMessage.get_system_message("old"),
        OpenAIMessage.get_user_message("u"),
    ]
    out = agent._set_first_message(msgs, "SYS3-{time}")
    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith("SYS3-")

    # Planner prompt insertion at index 1
    pm = [OpenAIMessage.get_system_message("s"), OpenAIMessage.get_user_message("u")]
    newm = agent._planner_prompt(pm.copy())
    assert newm[1]["role"] == "assistant"
    assert "step plan" in newm[1]["content"].lower()


def test_agent_run_tool_loop_calls_tool_and_inserts_summary():
    async def _run():
        # Prepare a tool and track invocations
        calls = {}

        def echo_tool(dedup_policy: DedupPolicy, **kwargs):
            calls["used"] = True
            return {"finished": True, "echo": kwargs}

        tool = AgentTool(
            name="echo_tool",
            description="Echo arguments",
            parameters=[],
            agent_call=echo_tool,
        )

        # Fake OpenAI that returns a single tool-call turn, then a summary
        client = FakeOpenAI(
            tool_name="echo_tool",
            tool_args={"hello": "world"},
            tool_usage=(3, 4),
            summary_text="Summary: All good",
            summary_usage=(2, 1),
        )

        agent = Agent(
            client=client,  # type: ignore[arg-type]
            model="gpt-x",
            tools=[tool],
            tool_prompt="TOOLS: {tools}",
            no_tools_prompt="NO TOOLS {tools}",
            max_rounds=2,
        )

        msgs = [OpenAIMessage.get_user_message("How are you?")]
        out_messages, usage = await agent.run_tool_loop(
            msgs, summary_tools=True, on_tool_call=None
        )

        # Assert the tool was invoked
        assert calls.get("used") is True

        # Assert the agent inserted a summary assistant message after the last user message
        # The run_tool_loop augments the ORIGINAL messages with one assistant summary
        assert len(out_messages) == 2
        assert out_messages[0]["role"] == "user"
        assert out_messages[1]["role"] == "assistant"
        assert (
            "Some useful information to respond to the user query:"
            in out_messages[1]["content"]
        )
        assert "Summary: All good" in out_messages[1]["content"]

        # Token usage is the sum of tool-turn usage + summary usage
        assert usage["prompt_tokens"] == 3 + 2
        assert usage["completion_tokens"] == 4 + 1
        assert usage["total_tokens"] == (3 + 4) + (2 + 1)

    asyncio.run(_run())


def test_agent_exec_and_select_tool_unknown_returns_error():
    async def _run():
        client = FakeOpenAI()
        agent = Agent(
            client=client,  # type: ignore[arg-type]
            model="gpt-x",
            tools=[],
            tool_prompt="TOOLS: {tools}",
            no_tools_prompt="NO TOOLS {tools}",
        )
        res = await agent.exec_and_select_tool("nonexistent", foo=1)
        assert "error" in res
        assert res["error"]["type"] == "UnknownTool"

    asyncio.run(_run())


def test_agent_get_response_no_tools_streaming_collects_chunks_and_usage():
    async def _run():
        # Streaming: "He", "llo", "!", usage per chunk: (0 prompt, 1 completion)
        client = FakeOpenAI(
            stream_chunks=["He", "llo", "!"], stream_usage_per_chunk=(0, 1)
        )
        agent = Agent(
            client=client,  # type: ignore[arg-type]
            model="gpt-x",
            tools=[],
            tool_prompt="TOOLS: {tools}",
            no_tools_prompt="NO TOOLS {tools}",
        )

        chunks = []

        async def on_chunk(ch: str):
            chunks.append(ch)

        msgs = [OpenAIMessage.get_user_message("ping")]
        new_messages, usage = await agent.get_response_no_tools(
            msgs, response_while_thinking=False, on_chunk=on_chunk, on_finish=None
        )

        # System prompt was removed; an assistant message with joined content added
        assert new_messages[0]["role"] == "user"
        assert new_messages[1]["role"] == "assistant"
        assert new_messages[1]["content"] == "Hello!"

        # Callback saw each chunk
        assert "".join(chunks) == "Hello!"

        # Usage accumulates from stream events
        # There are 3 events, each adds completion_tokens=1
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 3
        assert usage["total_tokens"] == 3

    asyncio.run(_run())


def test_retry_on_exception_sync_behavior():
    from ai_services.agents.utils import retry_on_exception

    # The current implementation raises immediately on exception; validate that behavior.
    calls = {"n": 0}

    @retry_on_exception(delays=[0.01, 0.01])
    def boom(x):
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom(1)
    # Called once (no retries due to immediate raise in impl)
    assert calls["n"] == 1

    @retry_on_exception(delays=[0.01])
    def ok(x):
        return x + 1

    assert ok(2) == 3


def test_retry_on_exception_async_behavior():
    async def _run():
        from ai_services.agents.utils import retry_on_exception

        calls = {"n": 0}

        @retry_on_exception(delays=[0.01, 0.02])
        async def async_boom():
            calls["n"] += 1
            raise RuntimeError("explode")

        with pytest.raises(RuntimeError):
            await async_boom()
        assert calls["n"] == 1

        @retry_on_exception(delays=[0.01])
        async def async_ok():
            return "ok"

        assert await async_ok() == "ok"

    asyncio.run(_run())
