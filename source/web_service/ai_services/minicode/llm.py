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

import json
import logging
from typing import Iterator

from .config import Config
from .events import AssistantTextDelta, AssistantTextEnd, AssistantTextStart, Event

logger = logging.getLogger(__name__)


def _estimate_tokens(obj: object) -> int:
    """Rough, dependency-free token estimate (~4 chars/token).

    Used ONLY as a fallback when the provider does not report usage, so a real
    model call is never recorded as zero tokens (the historic silent undercount).
    An approximation beats dropping the spend entirely.
    """
    if not obj:
        return 0
    if isinstance(obj, str):
        text = obj
    else:
        try:
            text = json.dumps(obj, ensure_ascii=False)
        except Exception:
            text = str(obj)
    return (len(text) + 3) // 4


def _finalize_usage(
    raw: dict | None,
    messages: list[dict],
    content: str,
    tool_calls: list[dict],
) -> dict:
    """Normalize a step's token usage so it is never silently lost.

    - If the provider reported usage, trust it but keep ``total_tokens`` at least
      ``prompt + completion`` (some endpoints send only the aggregate, or fold
      reasoning tokens into completion).
    - If it reported nothing usable, estimate from the payload and warn, so a
      call that really happened is never logged as zero tokens.
    """
    if raw:
        prompt = raw["prompt_tokens"]
        completion = raw["completion_tokens"]
        total = max(raw["total_tokens"], prompt + completion)
        if prompt or completion or total:
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
            }

    prompt = _estimate_tokens(messages)
    completion = _estimate_tokens(content) + _estimate_tokens(tool_calls)
    logger.warning(
        "LLM step returned no token usage; estimating ~%d prompt / %d completion tokens",
        prompt,
        completion,
    )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


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
        raw_usage: dict | None = None

        for chunk in stream:
            # The final usage chunk (include_usage) carries usage and empty choices.
            cu = getattr(chunk, "usage", None)
            if cu is not None:
                raw_usage = {
                    "prompt_tokens": int(getattr(cu, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(cu, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(cu, "total_tokens", 0) or 0),
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
        full_text = "".join(content)
        usage = _finalize_usage(raw_usage, messages, full_text, ordered)
        return {"content": full_text, "tool_calls": ordered, "usage": usage}
