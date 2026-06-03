"""Herramientas de shell sobre la VM: bash (foreground/background) + process.

Adaptación Pequeroku: los comandos corren en la VM del usuario vía
``VMServiceClient``, no en el servidor de Django.

- ``bash`` foreground → ``execute_sh`` (un round-trip SSH síncrono con timeout).
- ``bash`` background=true → ``start_process``: lanza el comando **detached** con
  ``setsid``, así SOBREVIVE al turno (y al cierre del agente). Es la forma de dejar
  un servicio corriendo de manera autónoma (p.ej. ``python3 main.py``,
  ``docker compose up``). Devuelve un ``job_id`` para seguirlo.
- ``process`` → consulta el estado / log de un job de background, o lo detiene.
"""
from __future__ import annotations

import time

from .base import Tool, ToolContext, truncate
from . import vm

# Tope de timeout foreground: el cliente HTTP del VMServiceClient corta a los 30s,
# así que dejamos margen. Para algo más largo o un servicio → background=true.
MAX_FOREGROUND_SECONDS = 25


class BashTool(Tool):
    name = "bash"
    description = (
        "Execute a shell command in the VM working directory (/app) and return its "
        "combined stdout/stderr. Use for builds, tests, git, installs and running "
        "scripts. Avoid interactive commands (they will hang).\n"
        "Foreground commands are capped at ~25s. Set background=true for anything "
        "longer or for long-running processes (dev servers, watchers, `docker compose "
        "up`): it launches the command detached, returns immediately with a job_id, "
        "and KEEPS RUNNING after this turn. Check it or stop it with the `process` tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "description": {"type": "string", "description": "Short description of what it does."},
            "timeout": {"type": "integer", "description": "Foreground timeout in milliseconds (default 25000, max ~25000)."},
            "background": {"type": "boolean", "description": "Run detached and return immediately (for servers / long jobs)."},
        },
        "required": ["command"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        command = args["command"]

        if args.get("background"):
            return self._run_background(client, cid, command)

        timeout_ms = args.get("timeout")
        secs = (int(timeout_ms) / 1000) if timeout_ms else float(
            getattr(ctx.config, "foreground_timeout", MAX_FOREGROUND_SECONDS)
        )
        secs = max(1, min(int(secs), MAX_FOREGROUND_SECONDS))

        resp = client.execute_sh(cid, command, timeout=secs)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "command failed or timed out"
            vm.audit("exec_command", cid, "Exec command", {"command": command}, success=False)
            return (
                f"Error: {reason}. Si es un servidor o un proceso largo (>{MAX_FOREGROUND_SECONDS}s), "
                "relánzalo con background=true."
            )

        out = (str(resp.get("stdout") or "")) + (str(resp.get("stderr") or ""))
        vm.audit("exec_command", cid, "Exec command", {"command": command})
        return truncate(out, from_tail=True) or "(sin salida)"

    # ------------------------------------------------------------------ #
    def _run_background(self, client, cid: str, command: str) -> str:
        resp = client.start_process(cid, command)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "could not start process"
            vm.audit("exec_command", cid, "Start background process", {"command": command}, success=False)
            return f"Error al lanzar en background: {reason}"

        job_id = resp.get("job_id", "")
        pid = resp.get("pid")
        log_path = resp.get("log_path", "")

        # Margen para detectar fallos de arranque y capturar la primera salida.
        time.sleep(0.7)
        status, log = "running", ""
        try:
            st = client.process_status(cid, job_id, lines=50)
            st = st if isinstance(st, dict) else {}
            status = st.get("status", "running")
            log = st.get("log", "")
        except Exception:
            pass

        vm.audit("exec_command", cid, "Start background process", {"command": command, "job_id": job_id})
        msg = (
            f"Lanzado en background. job_id={job_id} pid={pid} status={status}.\n"
            f"Log: {log_path}\n"
            f'Ver salida: process(job_id="{job_id}", action="status")  ·  '
            f'Detener: process(job_id="{job_id}", action="stop")'
        )
        if log.strip():
            msg += f"\n--- primera salida ---\n{truncate(log, from_tail=True)}"
        return msg


class ProcessTool(Tool):
    name = "process"
    description = (
        "Inspect or stop a background job started by bash(background=true). "
        "action='status' returns whether it is still running plus the tail of its log; "
        "action='stop' terminates it (SIGTERM to its process group)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job id returned by bash(background=true)."},
            "action": {"type": "string", "enum": ["status", "stop"], "description": "What to do (default: status)."},
            "lines": {"type": "integer", "description": "Trailing log lines for status (default 80)."},
        },
        "required": ["job_id"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        job_id = str(args.get("job_id", "")).strip()
        if not job_id:
            return "Error: falta job_id."
        action = args.get("action", "status")

        if action == "stop":
            resp = client.stop_process(cid, job_id)
            resp = resp if isinstance(resp, dict) else {}
            vm.audit("exec_command", cid, "Stop background process", {"job_id": job_id})
            if resp.get("ok"):
                return f"Job {job_id} detenido."
            return f"No se pudo detener el job {job_id}: {resp.get('reason') or 'desconocido'}."

        lines = int(args.get("lines", 80) or 80)
        resp = client.process_status(cid, job_id, lines=lines)
        resp = resp if isinstance(resp, dict) else {}
        status = resp.get("status", "unknown")
        pid = resp.get("pid")
        log = resp.get("log", "")
        vm.audit("exec_command", cid, "Background process status", {"job_id": job_id})
        header = f"job_id={job_id} status={status} pid={pid}"
        if log.strip():
            return f"{header}\n--- log ---\n{truncate(log, from_tail=True)}"
        return f"{header}\n(sin log todavía)"
