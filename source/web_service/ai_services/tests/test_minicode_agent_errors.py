"""Error-handling / resilience tests for the agent loop (minicode/agent.py).

These exercise the loop's promise that NOTHING a tool does brings the turn down,
and that the history stays valid even when a tool raises, returns bad JSON, is
unknown, or the user interrupts mid-turn.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ai_services.minicode.config import Config
from ai_services.minicode.session import Session
from ai_services.minicode.agent import Agent
from ai_services.minicode.events import (
    AssistantTextStart,
    AssistantTextDelta,
    AssistantTextEnd,
    ToolCallStarted,
    ToolResult,
    TodosUpdated,
    SubagentStarted,
    SubagentFinished,
    Info,
    Error,
)
from ai_services.minicode.tools.base import Tool


# --------------------------------------------------------------------------- #
# test doubles
# --------------------------------------------------------------------------- #
class FakeVMClient:
    def execute_sh(self, cid, command, timeout=None):
        return {"ok": True, "stdout": "", "stderr": "", "reason": ""}

    def read_file(self, cid, path):
        return {"found": False, "content": ""}


class FakeLLM:
    """Replays a scripted list of assistant messages, one per .stream() call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def stream(self, messages, tools):
        msg = self.script[self.calls]
        self.calls += 1
        content = msg.get("content") or ""
        if content:
            yield AssistantTextStart()
            yield AssistantTextDelta(text=content)
            yield AssistantTextEnd()
        return msg


def _tc(tool_id, name, arguments):
    return {"id": tool_id, "name": name, "arguments": arguments}


def _msg(content="", tool_calls=None):
    return {"content": content, "tool_calls": tool_calls or [], "usage": {}}


class BoomTool(Tool):
    name = "boom"
    description = "always raises"

    def execute(self, args, ctx):
        raise RuntimeError("kaboom")


class InterruptTool(Tool):
    name = "kbd"
    description = "raises KeyboardInterrupt"

    def execute(self, args, ctx):
        raise KeyboardInterrupt()


def make_config(custom_tools=None):
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = FakeVMClient()
    if custom_tools is not None:
        config.custom_tools = custom_tools
    return config


def run_agent(config, script, agent_type="build"):
    session = Session()
    session.add_user("go")
    agent = Agent(config, FakeLLM(script), agent_type=agent_type, session=session)
    events = list(agent.run())
    return events, session


# --------------------------------------------------------------------------- #
# a tool raising must NOT crash the loop
# --------------------------------------------------------------------------- #
def test_tool_exception_is_caught_and_fed_back():
    # The custom tool is appended to the build toolset (covers MCP/custom merge too).
    config = make_config(custom_tools=[BoomTool()])
    events, session = run_agent(
        config,
        [
            _msg(tool_calls=[_tc("c1", "boom", "{}")]),
            _msg(content="handled the error"),
        ],
    )
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert tool_results and "Error: kaboom" in tool_results[0].output
    # the loop continued to a clean final answer
    assert session.last_assistant_text() == "handled the error"
    # the history is valid: the tool_call got its answering tool message
    assert any(
        m["role"] == "tool" and "kaboom" in m["content"] for m in session.messages
    )


def test_invalid_json_arguments_returns_error_without_crashing():
    config = make_config()
    events, session = run_agent(
        config,
        [
            _msg(tool_calls=[_tc("c1", "read", "{not valid json")]),
            _msg(content="recovered"),
        ],
    )
    tool_msgs = [m for m in session.messages if m["role"] == "tool"]
    assert tool_msgs and "invalid JSON arguments" in tool_msgs[0]["content"]
    assert session.last_assistant_text() == "recovered"


def test_unknown_tool_returns_error():
    config = make_config()
    events, session = run_agent(
        config,
        [
            _msg(tool_calls=[_tc("c1", "ghost_tool", "{}")]),
            _msg(content="ok"),
        ],
    )
    results = [e for e in events if isinstance(e, ToolResult)]
    assert results and "unknown tool 'ghost_tool'" in results[0].output


# --------------------------------------------------------------------------- #
# interruption mid-turn keeps the history valid
# --------------------------------------------------------------------------- #
def test_keyboard_interrupt_aborts_and_skips_remaining_calls():
    config = make_config(custom_tools=[InterruptTool()])
    # Two tool calls in one step: the first interrupts, the second must be skipped
    # but STILL receive a tool-result (so the history is not left dangling).
    session = Session()
    session.add_user("go")
    agent = Agent(
        config,
        FakeLLM([_msg(tool_calls=[_tc("c1", "kbd", "{}"), _tc("c2", "read", "{}")])]),
        session=session,
    )
    events = list(agent.run())

    assert any(isinstance(e, Error) and "interrupted" in e.message for e in events)
    tool_msgs = {
        m["tool_call_id"]: m["content"] for m in session.messages if m["role"] == "tool"
    }
    assert "aborted by the user" in tool_msgs["c1"]
    assert "turn was aborted" in tool_msgs["c2"]  # skipped but answered


# --------------------------------------------------------------------------- #
# max-steps guard
# --------------------------------------------------------------------------- #
def test_max_steps_forces_stop_with_info_event():
    config = make_config()
    config.max_steps = 1
    # On the (only) step the model still asks for a tool; the loop must stop and
    # emit an Info instead of running it.
    events, session = run_agent(
        config, [_msg(content="partial", tool_calls=[_tc("c1", "read", "{}")])]
    )
    assert any(isinstance(e, Info) and "maximum" in e.message for e in events)
    # the tool was NOT executed (no ToolResult)
    assert not any(isinstance(e, ToolResult) for e in events)


# --------------------------------------------------------------------------- #
# streaming (generator) tool: events are forwarded, output returned
# --------------------------------------------------------------------------- #
def test_generator_tool_events_are_forwarded():
    config = make_config()
    events, session = run_agent(
        config,
        [
            _msg(
                tool_calls=[
                    _tc(
                        "c1",
                        "todowrite",
                        json.dumps({"todos": [{"content": "x", "status": "pending"}]}),
                    )
                ]
            ),
            _msg(content="planned"),
        ],
    )
    assert any(isinstance(e, TodosUpdated) for e in events)
    results = [e for e in events if isinstance(e, ToolResult)]
    assert results and "Updated task list" in results[0].output


# --------------------------------------------------------------------------- #
# subagent delegation via the task tool
# --------------------------------------------------------------------------- #
def test_task_tool_spawns_subagent_and_returns_report():
    config = make_config()
    # Shared FakeLLM script: main asks task -> subagent answers -> main answers.
    events, session = run_agent(
        config,
        [
            _msg(
                tool_calls=[
                    _tc(
                        "c1",
                        "task",
                        json.dumps(
                            {
                                "description": "look",
                                "prompt": "investigate",
                                "subagent_type": "explore",
                            }
                        ),
                    )
                ]
            ),
            _msg(content="subagent findings"),  # consumed by the subagent's loop
            _msg(content="final answer"),  # main agent's final reply
        ],
    )
    assert any(
        isinstance(e, SubagentStarted) and e.agent_type == "explore" for e in events
    )
    assert any(isinstance(e, SubagentFinished) for e in events)
    assert session.last_assistant_text() == "final answer"
    # the subagent's report was fed back as the task tool's result
    tool_msgs = [m for m in session.messages if m["role"] == "tool"]
    assert tool_msgs and "subagent findings" in tool_msgs[0]["content"]
