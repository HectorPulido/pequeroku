"""Estado de la conversación + memoria persistente + auto-reparación.

Guarda los mensajes en el formato exacto que entiende la API estilo OpenAI
(``role``/``content``/``tool_calls``/``tool``), que es lo que se reenvía al modelo
en cada vuelta del bucle. Persistir y releer este historial es justo lo que permite
que el modelo "vea" los resultados de sus herramientas en el paso siguiente.

Memoria: si ``memory_path`` está definido, ``save()`` vuelca la conversación a un
archivo JSON. Al iniciar en el mismo workdir, ``load()`` la recupera.

Resiliencia: ``sanitize()`` repara historiales rotos (un assistant con
``tool_calls`` sin su ``tool`` de respuesta), que de otro modo hacen que la API
devuelva 400 en TODAS las llamadas siguientes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_ABORTED = "Tool execution was interrupted; no result was produced."


class Session:
    def __init__(self, memory_path: Optional[str] = None) -> None:
        # Mensajes en formato OpenAI (sin incluir el system, que se antepone en cada vuelta).
        self.messages: list[dict] = []
        # Lista de tareas gestionada por la herramienta todowrite.
        self.todos: list[dict] = []
        self.memory_path = memory_path

    # -- mutaciones ------------------------------------------------------
    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: str, tool_calls: list[dict]) -> None:
        msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def last_assistant_text(self) -> str:
        for m in reversed(self.messages):
            if m["role"] == "assistant" and m.get("content"):
                return m["content"]
        return ""

    # -- resiliencia -----------------------------------------------------
    def sanitize(self) -> None:
        """Garantiza que cada ``assistant`` con ``tool_calls`` va seguido de un
        ``tool`` por cada id, y descarta mensajes ``tool`` huérfanos. Idempotente.
        """
        repaired: list[dict] = []
        msgs = self.messages
        n = len(msgs)
        i = 0
        while i < n:
            m = msgs[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                repaired.append(m)
                needed = [tc["id"] for tc in m["tool_calls"]]
                j = i + 1
                provided: dict = {}
                while j < n and msgs[j].get("role") == "tool":
                    provided[msgs[j].get("tool_call_id")] = msgs[j]
                    j += 1
                for tid in needed:
                    repaired.append(
                        provided.get(tid, {"role": "tool", "tool_call_id": tid, "content": _ABORTED})
                    )
                i = j
            elif m.get("role") == "tool":
                i += 1  # huérfano (sin assistant.tool_calls previo): se descarta
            else:
                repaired.append(m)
                i += 1
        self.messages = repaired

    # -- persistencia ----------------------------------------------------
    def save(self) -> None:
        if not self.memory_path:
            return
        self.sanitize()
        try:
            Path(self.memory_path).write_text(
                json.dumps({"messages": self.messages, "todos": self.todos}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass  # la memoria es best-effort; nunca debe tumbar el agente

    @classmethod
    def load(cls, memory_path: str) -> "Session":
        s = cls(memory_path=memory_path)
        try:
            data = json.loads(Path(memory_path).read_text(encoding="utf-8"))
            s.messages = data.get("messages", []) or []
            s.todos = data.get("todos", []) or []
            s.sanitize()
        except Exception:
            pass
        return s
