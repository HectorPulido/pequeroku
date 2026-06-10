"""Tests for the minicode LLM streaming adapter (no network).

Drives ``LLM.stream`` with a fake OpenAI client whose ``chat.completions.create``
returns scripted chunks, and asserts the emitted text events + the final
``{content, tool_calls, usage}`` it returns.
"""

from __future__ import annotations

from types import SimpleNamespace

from ai_services.minicode.config import Config
from ai_services.minicode.llm import LLM
from ai_services.minicode.events import (
    AssistantTextStart,
    AssistantTextDelta,
    AssistantTextEnd,
)


def _text_chunk(text):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))],
    )


def _tool_chunk(index, tid, name, args):
    tcd = SimpleNamespace(
        index=index,
        id=tid,
        function=SimpleNamespace(name=name, arguments=args),
    )
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tcd]))
        ],
    )


def _usage_chunk(p, c, t):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=p, completion_tokens=c, total_tokens=t),
        choices=[],
    )


def _make_llm(chunks):
    llm = LLM(Config(api_key="x", base_url="http://localhost:1", model="m"))
    llm.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: iter(chunks))
        )
    )
    return llm


def _drive(gen):
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        return events, stop.value


def test_stream_text_and_tool_call_and_usage():
    chunks = [
        _text_chunk("Hello"),
        _text_chunk(" world"),
        _tool_chunk(0, "c1", "bash", '{"command":"ls"}'),
        _usage_chunk(3, 4, 7),
    ]
    llm = _make_llm(chunks)
    events, result = _drive(llm.stream([{"role": "user", "content": "hi"}], tools=None))

    # text deltas wrapped by a single start/end
    assert isinstance(events[0], AssistantTextStart)
    assert isinstance(events[-1], AssistantTextEnd)
    deltas = [e.text for e in events if isinstance(e, AssistantTextDelta)]
    assert deltas == ["Hello", " world"]

    assert result["content"] == "Hello world"
    assert result["tool_calls"] == [
        {"id": "c1", "name": "bash", "arguments": '{"command":"ls"}'}
    ]
    assert result["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }


def test_stream_tool_call_only_has_no_text_events_and_fills_missing_id():
    # delta with no content, tool_call id empty -> id is synthesized as call_0
    chunks = [_tool_chunk(0, "", "read", '{"filePath":"a.py"}')]
    llm = _make_llm(chunks)
    events, result = _drive(llm.stream([], tools=[{"type": "function"}]))

    assert events == []  # no text -> no start/delta/end
    assert result["content"] == ""
    assert result["tool_calls"] == [
        {"id": "call_0", "name": "read", "arguments": '{"filePath":"a.py"}'}
    ]
    # No usage chunk from the provider -> usage is ESTIMATED (never None / zero for
    # a real call). Messages were empty so prompt is 0; the tool call drives a
    # small positive completion estimate.
    assert result["usage"]["prompt_tokens"] == 0
    assert result["usage"]["completion_tokens"] > 0
    assert result["usage"]["total_tokens"] == result["usage"]["completion_tokens"]


def test_stream_estimates_usage_when_provider_omits_it():
    # The stream has no _usage_chunk: the endpoint reported nothing. We must still
    # record a non-zero estimate instead of silently logging zero tokens.
    chunks = [_text_chunk("Hello world, this is a longer answer.")]
    llm = _make_llm(chunks)
    messages = [{"role": "user", "content": "a fairly long user prompt to estimate"}]
    _events, result = _drive(llm.stream(messages, tools=None))

    usage = result["usage"]
    assert usage is not None
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_stream_total_tokens_never_below_prompt_plus_completion():
    # Some endpoints under-report the aggregate; total must not drop below parts.
    chunks = [_text_chunk("hi"), _usage_chunk(3, 4, 0)]
    llm = _make_llm(chunks)
    _events, result = _drive(llm.stream([{"role": "user", "content": "x"}], tools=None))
    assert result["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,  # floored up from the reported 0
    }


def test_stream_accumulates_streamed_tool_arguments():
    # arguments arrive across several chunks for the same tool index
    chunks = [
        _tool_chunk(0, "c9", "bash", '{"comm'),
        _tool_chunk(0, "", "", 'and":"pytest"}'),
    ]
    llm = _make_llm(chunks)
    _events, result = _drive(llm.stream([], tools=[{"type": "function"}]))
    assert result["tool_calls"][0]["arguments"] == '{"command":"pytest"}'
    assert result["tool_calls"][0]["name"] == "bash"
