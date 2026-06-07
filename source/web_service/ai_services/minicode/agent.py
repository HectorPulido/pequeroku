"""The heart of the system: the agentic loop (opencode's ``runLoop``).

    think → call tools → see results → think again → ... → respond

The loop is driven by mini-code (not the SDK). On each turn it assembles the
context, asks the model for ONE step, runs the tools it requests, stores the
results in the session and starts over. It ends when the model responds with text
and WITHOUT requesting more tools.

INTERFACE DECOUPLING: ``Agent.run`` is a *generator*. It does not write to any
terminal; it ``yield``s core events (see ``minicode.events``). Whoever consumes it
(a terminal, a web app via SSE/websocket, an API) decides how to display them:

    for event in agent.run():
        render(event)            # or: queue.put(event), or: json.dumps(event_to_dict(event))

The final value (the text of the last response) is obtained via the generator's
``return``, which subagents capture with ``result = yield from sub.run()``.
"""

from __future__ import annotations

import json
from types import GeneratorType
from typing import Iterator

from .config import Config
from .context import build_system
from .events import (
    Error,
    Event,
    Info,
    SubagentFinished,
    SubagentStarted,
    ToolCallStarted,
    ToolResult,
    Usage,
)
from .llm import LLM
from .prompts import MAX_STEPS_PROMPT
from .session import Session
from .tools import ToolContext, tools_for
from .tools.base import truncate


class Agent:
    def __init__(
        self,
        config: Config,
        llm: LLM,
        agent_type: str = "build",
        session: Session | None = None,
        depth: int = 0,
    ) -> None:
        self.config = config
        self.llm = llm
        self.agent_type = agent_type
        self.tools = list(tools_for(agent_type))
        # MCP (remote) and custom (VM-side) tools are discovered once per turn and
        # offered to the agents that carry the full toolset; native tools win on a
        # name collision (and MCP wins over a custom tool of the same name).
        if agent_type in ("build", "general"):
            existing = {t.name for t in self.tools}
            for extra in (
                getattr(config, "mcp_tools", None) or [],
                getattr(config, "custom_tools", None) or [],
            ):
                for t in extra:
                    if t.name not in existing:
                        self.tools.append(t)
                        existing.add(t.name)
        self.tool_map = {t.name: t for t in self.tools}
        self.session = session or Session()
        # Nesting level (0 = main, >0 = subagent). Stamped on every event so the
        # interface can indent / label its origin.
        self.depth = depth

    # ------------------------------------------------------------------ #
    # the loop  (generator: yields events, returns the final text)
    # ------------------------------------------------------------------ #
    def run(self) -> Iterator[Event]:
        step = 0
        while True:
            step += 1
            last_step = step >= self.config.max_steps

            # 1) assemble context: system + the session's (repaired) history
            self.session.sanitize()  # safety net: we never send a broken history
            system = build_system(self.config, self.agent_type)
            messages = [{"role": "system", "content": system}, *self.session.messages]
            tools_schema = None if last_step else [t.schema for t in self.tools]
            if last_step:
                # on the last step we forbid tools and force a summary
                messages.append({"role": "system", "content": MAX_STEPS_PROMPT})

            # 2) one model step (streaming): we forward its text events
            msg = yield from self._forward(self.llm.stream(messages, tools_schema))
            self.session.add_assistant(msg["content"], msg["tool_calls"])

            # token count for this step (includes the subagents', which emit their
            # own Usage that bubbles up through the same stream)
            u = msg.get("usage")
            if u:
                yield Usage(
                    prompt_tokens=u.get("prompt_tokens", 0),
                    completion_tokens=u.get("completion_tokens", 0),
                    total_tokens=u.get("total_tokens", 0),
                    depth=self.depth,
                )

            # 3) exit condition? no tool-calls => the task is done
            if not msg["tool_calls"] or last_step:
                if last_step and msg["tool_calls"]:
                    yield Info(
                        message=f"(reached the maximum of {self.config.max_steps} steps)",
                        depth=self.depth,
                    )
                self.session.save()
                break

            # 4) run each tool and feed the result back.
            #    RESILIENCE KEY: every tool-call MUST receive its tool-result, even
            #    if the user hits Ctrl-C midway; otherwise the history becomes
            #    invalid and the API rejects everything that follows (an
            #    assistant.tool_calls with no answer). This is opencode's cleanup().
            interrupted = False
            for tc in msg["tool_calls"]:
                if interrupted:
                    self.session.add_tool_result(
                        tc["id"], "Tool skipped: the turn was aborted."
                    )
                    continue
                try:
                    output = yield from self._execute(tc)
                except KeyboardInterrupt:
                    output = "Tool execution aborted by the user (Ctrl-C)."
                    yield Error(message="(interrupted)", depth=self.depth)
                    interrupted = True
                self.session.add_tool_result(tc["id"], output)

            self.session.save()
            if interrupted:
                break

        return self.session.last_assistant_text()

    # ------------------------------------------------------------------ #
    # forwarding a child generator, sealing the depth
    # ------------------------------------------------------------------ #
    def _forward(self, gen: Iterator[Event]):
        """Forward the events of a child generator (LLM, tool), stamping our
        ``depth`` on the ones that don't have it yet, and return its final value.

        Events that already come from a subagent carry their own ``depth`` (not
        ``None``) and pass through untouched: they are not flattened.
        """
        while True:
            try:
                event = next(gen)
            except StopIteration as stop:
                return stop.value
            if event.depth is None:
                event.depth = self.depth
            yield event

    # ------------------------------------------------------------------ #
    # running a tool-call  (generator: yields events, returns output)
    # ------------------------------------------------------------------ #
    def _execute(self, tc: dict) -> Iterator[Event]:
        name = tc["name"]
        try:
            args = json.loads(tc["arguments"] or "{}")
        except json.JSONDecodeError as e:
            return f"Error: invalid JSON arguments ({e}). Rewrite the input."

        yield ToolCallStarted(name=name, args=args, depth=self.depth)
        tool = self.tool_map.get(name)
        if tool is None:
            output = f"Error: unknown tool '{name}'."
            yield ToolResult(name=name, output=output, depth=self.depth)
            return output

        ctx = ToolContext(
            config=self.config,
            session=self.session,
            spawn_subagent=self.spawn_subagent,
        )
        try:
            result = tool.execute(args, ctx)
            # A tool can be plain (returns str) or "streaming" (a generator that
            # yields events and returns the str). We forward those events.
            if isinstance(result, GeneratorType):
                output = yield from self._forward(result)
            else:
                output = result
        except Exception as e:  # no tool should ever bring the loop down
            output = f"Error: {e}"
        output = truncate(output)
        yield ToolResult(name=name, output=output, depth=self.depth)
        return output

    # ------------------------------------------------------------------ #
    # subagents: a child session with its own loop (isolation)
    # ------------------------------------------------------------------ #
    def spawn_subagent(self, agent_type: str, prompt: str) -> Iterator[Event]:
        """Generator: spawn a subagent, forward its events (at a deeper level) and
        return its final report."""
        yield SubagentStarted(agent_type=agent_type, prompt=prompt, depth=self.depth)
        sub = Agent(self.config, self.llm, agent_type=agent_type, depth=self.depth + 1)
        sub.session.add_user(prompt)
        result = yield from sub.run()
        yield SubagentFinished(agent_type=agent_type, depth=self.depth)
        return result or "(the subagent returned no text)"
