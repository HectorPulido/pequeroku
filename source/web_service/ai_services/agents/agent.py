import json
import inspect

from collections.abc import Awaitable
from typing import Any, Callable, TypeVar, ParamSpec, cast
from openai import OpenAI
from .models import AgentTool, OpenAIMessage, DedupPolicy, OpenAIChatMessage, TokenUsage
from .utils import retry_on_exception

DELAYS = [0.5, 1.0, 2.0, 4.0, 8.0]

P = ParamSpec("P")
T = TypeVar("T")


def _safe_preview(obj: Any, *, maxlen: int = 120) -> str:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        s = repr(obj)
        return s if len(s) <= maxlen else s[:maxlen] + "..."

    if hasattr(obj, "_meta"):
        pk = getattr(obj, "pk", None)
        return f"<{obj.__class__.__name__} pk={pk}>"

    if isinstance(obj, dict):
        keys = list(obj.keys())
        return f"<dict keys={keys[:10]}{'…' if len(keys) > 10 else ''}>"

    if isinstance(obj, (list, tuple, set)):
        sample = list(obj)[:3]
        return f"<{type(obj).__name__} len={len(obj)} sample={[type(x).__name__ for x in sample]}>"

    if callable(obj):
        return f"<callable {getattr(obj, '__name__', type(obj).__name__)}>"

    return f"<{type(obj).__name__}>"


def _usage(resp: Any) -> TokenUsage:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    prompt_tokens: int = getattr(usage, "prompt_tokens", 0)
    completion_tokens: int = getattr(usage, "completion_tokens", 0)
    total_tokens: int = getattr(
        usage, "total_tokens", prompt_tokens + completion_tokens
    )

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


async def _maybe_await(
    fn: Callable[P, Awaitable[T] | T] | None,
    error_msg: str,
    def_response: T,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    try:
        if fn is None:
            return def_response

        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):
            res = await cast(Awaitable[T], res)

        return cast(T, res)
    except Exception as e:
        print("[_maybe_await] Exception: ", e)
        print(error_msg)
        return def_response


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class Agent:
    PROMPT_SUMMARY: str = """
    Your task is to summarize all this information in a very objective way,
    always tailored to the query, do not invent anything and do not dare to lie.
    Respond on this format
    Query: <the user query>
    Summary: <the summary tailored to the query>
    """.strip()

    PROMPT_PLANNER: str = """
    Before taking actions, briefly outline a 1–{max_rounds} step plan, then proceed to call tools.
    Group multiple calls if possible, ask for permission if something is not safe, and keep edits and change minimal.
    """.strip()

    def _set_first_message(self, messages: list[OpenAIChatMessage], prompt: str):
        new_messages = messages.copy()
        system_prompt = OpenAIMessage.get_system_message(
            prompt.replace("{time}", _now_iso())
        )

        if len(new_messages) == 0:
            new_messages = cast(list[OpenAIChatMessage], [system_prompt])
            return new_messages

        if new_messages[0]["role"] == "system":
            new_messages[0] = system_prompt
            return new_messages

        new_messages.insert(0, system_prompt)
        return new_messages

    def _render_parts(self, calls: list[dict[str, Any]]):
        parts = ""
        for call in calls:
            parts += f"[{call['name']}]: {call['content']}\n"
        return parts

    def _planner_prompt(self, messages: list[OpenAIChatMessage]):
        new_messages = messages.copy()

        new_messages.insert(
            1,
            OpenAIMessage.get_assistant_message(
                self.PROMPT_PLANNER.replace("{max_rounds}", str(self.max_rounds))
            ),
        )
        return new_messages

    def _system_prompt_w_tools(self, messages: list[OpenAIChatMessage]):
        return self._set_first_message(
            messages, self.tool_prompt.replace("{tools}", self.tools_str)
        )

    def _system_prompt_wo_tools(self, messages: list[OpenAIChatMessage]):
        no_tools_prompt_tools = "YOU HAVE NO TOOLS, DO NOT TRY TO USE TOOLS IN ANY CONTEXT, THE INFO YOU HAVE IS ALL YOU HAVE"
        return self._set_first_message(
            messages,
            self.no_tools_prompt.replace(
                "{tools}",
                no_tools_prompt_tools,
            ),
        )

    def __init__(
        self,
        client: OpenAI,
        model: str,
        tools: list[AgentTool],
        tool_prompt: str,
        no_tools_prompt: str,
        max_rounds: int = 10,
        prompt_summary: str | None = None,
        prompt_planner: str | None = None,
    ):
        self.client: OpenAI = client
        self.model: str = model
        self.tools: list[dict[str, Any]] = [tool.generate_tool_dict() for tool in tools]
        self.callables: dict[str, Callable[..., Any]] = {
            tool.name: tool.agent_call for tool in tools
        }
        self.tools_str: str = AgentTool.render_agents(tools)
        self.max_rounds: int = max_rounds
        self.tool_prompt: str = tool_prompt
        self.no_tools_prompt: str = no_tools_prompt
        self.prompt_summary: str = prompt_summary or self.PROMPT_SUMMARY
        self.prompt_planner: str = prompt_planner or self.PROMPT_PLANNER

    async def exec_and_select_tool(self, name: str, **args: Any) -> dict[str, Any]:
        fn = self.callables.get(name)
        if not fn:
            err = {"error": {"type": "UnknownTool", "message": f"Unknown tool: {name}"}}
            print("tool_call unknown tool", name)
            return err  # type: ignore[return-value]

        error_msg = f"tool_call Exception tool={name}"
        def_response = {"error": {"type": "error", "message": error_msg}}
        return cast(
            dict[str, Any], await _maybe_await(fn, error_msg, def_response, **args)
        )

    async def run_tool_loop(
        self,
        messages: list[OpenAIChatMessage],
        summary_tools: bool,
        on_tool_call: Callable[..., Any] | None = None,
        **kwargs: Any,
    ):
        new_messages = self._planner_prompt(self._system_prompt_w_tools(messages))
        calls: list[dict[str, str]] = []
        dedup_policy = DedupPolicy()

        total_usage: TokenUsage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _ in range(self.max_rounds):
            _, finish_reason, tool_calls, content, usage = cast(
                tuple[Any, str, list[Any], str, TokenUsage],
                await self.get_response_tools(new_messages),
            )
            total_usage["prompt_tokens"] += usage["prompt_tokens"]
            total_usage["completion_tokens"] += usage["completion_tokens"]
            total_usage["total_tokens"] += usage["total_tokens"]

            if content:
                calls.append(
                    {
                        "name": "planning",
                        "content": content,
                    }
                )

            if not tool_calls or len(tool_calls) == 0:
                break

            for tool_call in tool_calls:
                tool = tool_call.function
                tool_name = cast(str, tool.name)
                tool_call_id = cast(str, tool_call.id)
                try:
                    args = cast(dict[str, Any], json.loads(tool.arguments or "{}"))
                except Exception:
                    args = {}

                new_kwargs = kwargs.copy()
                new_kwargs.update(args)
                new_kwargs["dedup_policy"] = dedup_policy

                # Callback for tool_call
                safe_kwargs = {k: _safe_preview(v) for k, v in new_kwargs.items()}
                error_msg = f"[run_tool_loop] tool_call Exception tool={tool_name} kwargs={safe_kwargs}"
                await _maybe_await(on_tool_call, error_msg, None, tool_name, **args)

                result = await self.exec_and_select_tool(tool_name, **new_kwargs)

                new_messages.append(
                    OpenAIMessage.get_tool_calling_message(
                        tool_call_id, tool_name, args
                    )
                )
                new_messages.append(
                    OpenAIMessage.get_tool_response_message(
                        tool_call_id, tool_name, result
                    )
                )
                calls.append(
                    {
                        "name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            if finish_reason in ("stop", "length", None, "content_filter"):
                print(f"[AGENT] STOP_REASON: {finish_reason}")
                break

        if len(calls) < 2:
            return messages, total_usage

        if summary_tools:
            summary, usage = cast(
                tuple[str, TokenUsage],
                await self.get_response_summary(calls, messages[-1]["content"]),
            )
            total_usage["prompt_tokens"] += usage["prompt_tokens"]
            total_usage["completion_tokens"] += usage["completion_tokens"]
            total_usage["total_tokens"] += usage["total_tokens"]
        else:
            summary = self._render_parts(calls)

        # Insert the summary right after the latest user message
        insert_at = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                insert_at = i + 1
                break
        if insert_at is None:
            insert_at = len(messages)

        messages.insert(
            insert_at,
            OpenAIMessage.get_assistant_message(
                f"Some useful information to respond to the user query: {summary}"
            ),
        )

        return messages, total_usage

    async def ask(
        self,
        query: str,
        context: dict[str, Any],
        messages: list[OpenAIChatMessage] | None = None,
        on_chunk: Callable[[str], Any] | None = None,
        on_tool_call: Callable[..., Any] | None = None,
    ):
        if messages is None:
            messages = []
        messages.append(OpenAIMessage.get_user_message(query))

        messages, lu = await self.run_tool_loop(messages, True, on_tool_call, **context)
        messages, ru = cast(
            tuple[list[OpenAIChatMessage], TokenUsage],
            await self.get_response_no_tools(messages, False, on_chunk, None),
        )

        total_usage: TokenUsage = {
            "prompt_tokens": lu["prompt_tokens"] + ru["prompt_tokens"],
            "completion_tokens": lu["completion_tokens"] + ru["completion_tokens"],
            "total_tokens": lu["total_tokens"] + ru["total_tokens"],
        }

        return messages, total_usage

    @retry_on_exception(delays=DELAYS)
    async def get_response_summary(self, calls: list[dict[str, str]], query: str):
        parts = self._render_parts(calls)
        summary_user_prompt = f"Return me the summary of <parts>{parts}</parts> tailored to this query <query>{query}</query>"

        messages = [
            OpenAIMessage.get_system_message(self.PROMPT_SUMMARY),
            OpenAIMessage.get_user_message(summary_user_prompt),
        ]

        resp = self.client.chat.completions.create(
            messages=cast(Any, messages),
            model=self.model,
            stream=False,
        )
        content = resp.choices[0].message.content
        return content, _usage(resp)

    @retry_on_exception(delays=DELAYS)
    async def get_response_tools(self, new_messages: list[OpenAIChatMessage]):
        resp = self.client.chat.completions.create(
            messages=cast(Any, new_messages),
            model=self.model,
            tools=cast(Any, self.tools),
            tool_choice="auto",
            stream=False,
        )
        choice = resp.choices[0]
        message = choice.message
        content = cast(str, choice.message.content)
        finish_reason: str | None = getattr(choice, "finish_reason", None)
        tool_calls: list[dict[str, Any]] = getattr(message, "tool_calls", [])

        return resp, finish_reason, tool_calls, content, _usage(resp)

    @retry_on_exception(delays=DELAYS)
    async def get_response_no_tools(
        self,
        messages: list[OpenAIChatMessage],
        response_while_thinking: bool,
        on_chunk: Callable[[str], Any] | None = None,
        on_finish: Callable[[str], Any] | None = None,
    ):
        new_messages = self._system_prompt_wo_tools(messages.copy())
        buff = ""
        stream = self.client.chat.completions.create(
            messages=cast(Any, new_messages),
            model=self.model,
            stream=True,
            response_format={"type": "text"},
            stream_options={"include_usage": True},
        )

        total_usage: TokenUsage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for evt in stream:
            usage = _usage(evt)
            total_usage["prompt_tokens"] += usage["prompt_tokens"]
            total_usage["completion_tokens"] += usage["completion_tokens"]
            total_usage["total_tokens"] += usage["total_tokens"]

            if not evt or not evt.choices or len(evt.choices) == 0:
                continue

            chunk = evt.choices[0].delta.content
            if not chunk:
                continue
            buff += chunk
            thinking = "<think>" in buff and "</think>" not in buff

            # Callback chunk
            if (not thinking or response_while_thinking) and on_chunk is not None:
                error_msg = "[get_response_no_tools] callback on on_chunk error"
                await _maybe_await(on_chunk, error_msg, None, chunk)

        if not buff.strip():
            del new_messages[-1]
            return new_messages, total_usage

        # Callback finish
        if on_finish is not None:
            error_msg = "[get_response_no_tools] callback on on_finish error"
            await _maybe_await(on_finish, error_msg, None, buff)

        new_messages.append(OpenAIMessage.get_assistant_message(buff))
        # Delete the system prompt
        del new_messages[0]

        return new_messages, total_usage
