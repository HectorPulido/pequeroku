"""Puente con el modelo (API estilo OpenAI), en streaming.

Equivale a ``session/llm.ts`` + el adaptador del stream de opencode, pero mucho
más simple. Punto CLAVE de la arquitectura: NO delegamos el bucle multi-paso al
SDK. Cada llamada a ``stream`` hace UN solo paso (una respuesta del modelo, que
puede incluir tool-calls). El bucle "seguir hasta terminar" lo lleva ``Agent``.

``stream`` es un *generador*: hace ``yield`` de eventos de texto (sin saber nada
de la interfaz) y, al terminar, ``return`` del mensaje final. El ``Agent`` lo
consume con ``msg = yield from llm.stream(...)``.
"""

from __future__ import annotations

from typing import Iterator

from .config import Config
from .events import AssistantTextDelta, AssistantTextEnd, AssistantTextStart, Event


class LLM:
    def __init__(self, config: Config) -> None:
        from openai import OpenAI  # import perezoso: las tools no necesitan openai

        self.config = config
        # api_key dummy para endpoints locales que no la exigen (Ollama, etc.).
        self.client = OpenAI(
            api_key=config.api_key or "sk-no-key", base_url=config.base_url
        )

    def stream(self, messages: list[dict], tools: list[dict] | None) -> Iterator[Event]:
        """Un paso del modelo. Hace ``yield`` del texto en vivo (como eventos) y
        acumula los tool-calls.

        Generador: emite ``AssistantText*`` y ``return`` del mensaje final
        ``{"content": str, "tool_calls": [...], "usage": {...}|None}``.
        """
        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
        }
        # Pide el uso de tokens en el último chunk del stream. Si algún endpoint
        # no lo soporta, simplemente no llegará y el conteo quedará en cero.
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
            # El chunk final de uso (include_usage) trae usage y choices vacío.
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
        for i, tc in enumerate(ordered):  # garantiza un id no vacío
            if not tc["id"]:
                tc["id"] = f"call_{i}"
        return {"content": "".join(content), "tool_calls": ordered, "usage": usage}
