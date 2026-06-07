"""Bridge to the model (OpenAI-style API), streaming.

Equivalent to opencode's ``session/llm.ts`` + the stream adapter, but much
simpler. KEY architectural point: we do NOT delegate the multi-step loop to the
SDK. Each call to ``stream`` does ONE single step (one model response, which may
include tool-calls). The "keep going until done" loop is driven by ``Agent``.

``stream`` is a *generator*: it ``yield``s text events (knowing nothing about the
interface) and, when finished, ``return``s the final message. The ``Agent``
consumes it with ``msg = yield from llm.stream(...)``.
"""

from __future__ import annotations

from typing import Iterator

from .config import Config
from .events import AssistantTextDelta, AssistantTextEnd, AssistantTextStart, Event


class LLM:
    def __init__(self, config: Config) -> None:
        from openai import OpenAI  # lazy import: the tools don't need openai

        self.config = config
        # dummy api_key for local endpoints that don't require it (Ollama, etc.).
        self.client = OpenAI(
            api_key=config.api_key or "sk-no-key", base_url=config.base_url
        )

    def stream(self, messages: list[dict], tools: list[dict] | None) -> Iterator[Event]:
        """One model step. ``yield``s the text live (as events) and accumulates the
        tool-calls.

        Generator: emits ``AssistantText*`` and ``return``s the final message
        ``{"content": str, "tool_calls": [...], "usage": {...}|None}``.
        """
        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
        }
        # Ask for token usage in the stream's last chunk. If an endpoint does not
        # support it, it simply won't arrive and the count stays at zero.
        kwargs["stream_options"] = {"include_usage": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        if self.config.max_output_tokens:
            kwargs["max_tokens"] = self.config.max_output_tokens

        stream = self.client.chat.completions.create(**kwargs)

        content: list[str] = []
        tool_calls: dict[int, dict] = {}
        started_text = False
        usage: dict | None = None

        for chunk in stream:
            # The final usage chunk (include_usage) carries usage and empty choices.
            cu = getattr(chunk, "usage", None)
            if cu is not None:
                usage = {
                    "prompt_tokens": getattr(cu, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(cu, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(cu, "total_tokens", 0) or 0,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue

            if delta.content:
                if not started_text:
                    yield AssistantTextStart()
                    started_text = True
                yield AssistantTextDelta(text=delta.content)
                content.append(delta.content)

            for tcd in delta.tool_calls or []:
                acc = tool_calls.setdefault(
                    tcd.index, {"id": "", "name": "", "arguments": ""}
                )
                if tcd.id:
                    acc["id"] = tcd.id
                if tcd.function:
                    if tcd.function.name:
                        acc["name"] = tcd.function.name
                    if tcd.function.arguments:
                        acc["arguments"] += tcd.function.arguments

        if started_text:
            yield AssistantTextEnd()

        ordered = [tool_calls[k] for k in sorted(tool_calls)]
        for i, tc in enumerate(ordered):  # guarantee a non-empty id
            if not tc["id"]:
                tc["id"] = f"call_{i}"
        return {"content": "".join(content), "tool_calls": ordered, "usage": usage}
