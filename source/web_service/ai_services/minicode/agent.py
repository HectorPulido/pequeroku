"""El corazón del sistema: el bucle agéntico (``runLoop`` de opencode).

    pensar → llamar herramientas → ver resultados → volver a pensar → ... → responder

El bucle lo controla mini-code (no el SDK). En cada vuelta ensambla el contexto,
pide UN paso al modelo, ejecuta las herramientas que pida, guarda los resultados
en la sesión y vuelve a empezar. Termina cuando el modelo responde con texto y
SIN pedir más herramientas.

DESACOPLE DE LA INTERFAZ: ``Agent.run`` es un *generador*. No escribe en ninguna
terminal; hace ``yield`` de eventos del core (ver ``minicode.events``). Quien lo
consume (una terminal, una web vía SSE/websocket, una API) decide cómo mostrarlos:

    for event in agent.run():
        render(event)            # o: queue.put(event), o: json.dumps(event_to_dict(event))

El valor final (texto de la última respuesta) se obtiene con ``return`` del
generador, que los subagentes capturan con ``result = yield from sub.run()``.
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
        # Nivel de anidamiento (0 = principal, >0 = subagente). Se estampa en cada
        # evento para que la interfaz pueda indentar / etiquetar el origen.
        self.depth = depth

    # ------------------------------------------------------------------ #
    # el bucle  (generador: hace yield de eventos, return del texto final)
    # ------------------------------------------------------------------ #
    def run(self) -> Iterator[Event]:
        step = 0
        while True:
            step += 1
            last_step = step >= self.config.max_steps

            # 1) ensamblar contexto: system + historial (reparado) de la sesión
            self.session.sanitize()  # red de seguridad: nunca enviamos un historial roto
            system = build_system(self.config, self.agent_type)
            messages = [{"role": "system", "content": system}, *self.session.messages]
            tools_schema = None if last_step else [t.schema for t in self.tools]
            if last_step:
                # en el último paso prohibimos herramientas y forzamos un resumen
                messages.append({"role": "system", "content": MAX_STEPS_PROMPT})

            # 2) un paso del modelo (streaming): reenviamos sus eventos de texto
            msg = yield from self._forward(self.llm.stream(messages, tools_schema))
            self.session.add_assistant(msg["content"], msg["tool_calls"])

            # conteo de tokens de este paso (incluye los de los subagentes, que
            # emiten su propio Usage y burbujea por el mismo stream)
            u = msg.get("usage")
            if u:
                yield Usage(
                    prompt_tokens=u.get("prompt_tokens", 0),
                    completion_tokens=u.get("completion_tokens", 0),
                    total_tokens=u.get("total_tokens", 0),
                    depth=self.depth,
                )

            # 3) ¿condición de salida? sin tool-calls => la tarea está hecha
            if not msg["tool_calls"] or last_step:
                if last_step and msg["tool_calls"]:
                    yield Info(
                        message=f"(reached the maximum of {self.config.max_steps} steps)",
                        depth=self.depth,
                    )
                self.session.save()
                break

            # 4) ejecutar cada herramienta y realimentar el resultado.
            #    CLAVE de resiliencia: cada tool-call DEBE recibir su tool-result,
            #    aunque el usuario pulse Ctrl-C a mitad; si no, el historial queda
            #    inválido y la API rechaza todo lo siguiente (assistant.tool_calls
            #    sin su respuesta). Es el equivalente al cleanup() de opencode.
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
    # reenvío de un generador hijo, sellando la profundidad
    # ------------------------------------------------------------------ #
    def _forward(self, gen: Iterator[Event]):
        """Reenvía los eventos de un generador hijo (LLM, tool) estampando nuestra
        ``depth`` en los que aún no la tienen, y devuelve su valor final.

        Los eventos que ya vienen de un subagente traen su propia ``depth`` (no es
        ``None``) y pasan intactos: no se aplanan.
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
    # ejecución de una tool-call  (generador: yield eventos, return output)
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
            # Una tool puede ser normal (devuelve str) o "streaming" (un generador
            # que hace yield de eventos y return del str). Reenviamos esos eventos.
            if isinstance(result, GeneratorType):
                output = yield from self._forward(result)
            else:
                output = result
        except Exception as e:  # ninguna tool debería tumbar el bucle
            output = f"Error: {e}"
        output = truncate(output)
        yield ToolResult(name=name, output=output, depth=self.depth)
        return output

    # ------------------------------------------------------------------ #
    # subagentes: una sesión hija con su propio bucle (aislamiento)
    # ------------------------------------------------------------------ #
    def spawn_subagent(self, agent_type: str, prompt: str) -> Iterator[Event]:
        """Generador: lanza un subagente, reenvía sus eventos (con más profundidad)
        y devuelve su reporte final."""
        yield SubagentStarted(agent_type=agent_type, prompt=prompt, depth=self.depth)
        sub = Agent(self.config, self.llm, agent_type=agent_type, depth=self.depth + 1)
        sub.session.add_user(prompt)
        result = yield from sub.run()
        yield SubagentFinished(agent_type=agent_type, depth=self.depth)
        return result or "(the subagent returned no text)"
