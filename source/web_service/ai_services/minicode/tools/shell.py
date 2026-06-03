"""Shell tools over the VM: bash (foreground/background) + process.

Pequeroku adaptation: commands run inside the user's VM via ``VMServiceClient``,
not on the Django server.

- ``bash`` foreground → ``execute_sh`` (one synchronous SSH round-trip with timeout).
- ``bash`` background=true → ``start_process``: launches the command detached with
  ``setsid``, so it SURVIVES the turn (and the agent closing). This is how to leave a
  service running autonomously (e.g. ``python3 main.py``, ``docker compose up``).
  Returns a ``job_id`` to follow it.
- ``process`` → check the status/log of a background job, or stop it.

Commands run in the workspace (``/app``) by default: the SSH login directory is the
home (``/root``), so every command is wrapped in ``cd <workdir> && …`` — the agent
never has to cd manually. Override with the ``workdir`` arg.
"""

from __future__ import annotations

import shlex
import time

from .base import Tool, ToolContext, truncate
from . import vm

# Foreground timeout ceiling: the VMServiceClient HTTP call cuts off at 30s, so we
# leave margin. For anything longer or a service → background=true.
MAX_FOREGROUND_SECONDS = 25


class BashTool(Tool):
    name = "bash"
    description = (
        "Execute a shell command in the VM and return its combined stdout/stderr. "
        "Use for builds, tests, git, installs and running scripts. Avoid interactive "
        "commands (they will hang).\n"
        "Commands run in the workspace `/app` by default (you do NOT need to `cd /app` "
        "first); pass `workdir` to run elsewhere.\n"
        "Foreground commands are capped at ~25s. Set background=true for anything "
        "longer or for long-running processes (dev servers, watchers, `docker compose "
        "up`): it launches the command detached, returns immediately with a job_id, "
        "and KEEPS RUNNING after this turn. Check it or stop it with the `process` tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "description": {
                "type": "string",
                "description": "Short description of what it does.",
            },
            "workdir": {
                "type": "string",
                "description": "Directory to run in (default: /app).",
            },
            "timeout": {
                "type": "integer",
                "description": "Foreground timeout in milliseconds (default 25000, max ~25000).",
            },
            "background": {
                "type": "boolean",
                "description": "Run detached and return immediately (for servers / long jobs).",
            },
        },
        "required": ["command"],
    }

    @staticmethod
    def _in_workdir(args: dict, ctx: ToolContext, command: str) -> str:
        """Wrap the command so it runs in the workspace (/app) instead of the SSH
        login home (/root). Override with the ``workdir`` arg."""
        workdir = (
            args.get("workdir") or getattr(ctx.config, "workdir", "/app") or "/app"
        )
        return f"cd {shlex.quote(str(workdir))} && {command}"

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        command = args["command"]
        run_cmd = self._in_workdir(args, ctx, command)

        if args.get("background"):
            return self._run_background(client, cid, run_cmd, command)

        timeout_ms = args.get("timeout")
        secs = (
            (int(timeout_ms) / 1000)
            if timeout_ms
            else float(
                getattr(ctx.config, "foreground_timeout", MAX_FOREGROUND_SECONDS)
            )
        )
        secs = max(1, min(int(secs), MAX_FOREGROUND_SECONDS))

        resp = client.execute_sh(cid, run_cmd, timeout=secs)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "command failed or timed out"
            vm.audit(
                "exec_command", cid, "Exec command", {"command": command}, success=False
            )
            return (
                f"Error: {reason}. If this is a server or a long-running command "
                f"(>{MAX_FOREGROUND_SECONDS}s), relaunch it with background=true."
            )

        out = (str(resp.get("stdout") or "")) + (str(resp.get("stderr") or ""))
        vm.audit("exec_command", cid, "Exec command", {"command": command})
        return truncate(out, from_tail=True) or "(no output)"

    # ------------------------------------------------------------------ #
    def _run_background(self, client, cid: str, run_cmd: str, command: str) -> str:
        resp = client.start_process(cid, run_cmd)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "could not start process"
            vm.audit(
                "exec_command",
                cid,
                "Start background process",
                {"command": command},
                success=False,
            )
            return f"Error launching in background: {reason}"

        job_id = resp.get("job_id", "")
        pid = resp.get("pid")
        log_path = resp.get("log_path", "")

        # Brief beat to catch startup failures and capture the first output.
        time.sleep(0.7)
        status, log = "running", ""
        try:
            st = client.process_status(cid, job_id, lines=50)
            st = st if isinstance(st, dict) else {}
            status = st.get("status", "running")
            log = st.get("log", "")
        except Exception:
            pass

        vm.audit(
            "exec_command",
            cid,
            "Start background process",
            {"command": command, "job_id": job_id},
        )
        msg = (
            f"Started in background. job_id={job_id} pid={pid} status={status}.\n"
            f"Log: {log_path}\n"
            f'Check output: process(job_id="{job_id}", action="status")  ·  '
            f'Stop: process(job_id="{job_id}", action="stop")'
        )
        if log.strip():
            msg += f"\n--- first output ---\n{truncate(log, from_tail=True)}"
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
            "job_id": {
                "type": "string",
                "description": "Job id returned by bash(background=true).",
            },
            "action": {
                "type": "string",
                "enum": ["status", "stop"],
                "description": "What to do (default: status).",
            },
            "lines": {
                "type": "integer",
                "description": "Trailing log lines for status (default 80).",
            },
        },
        "required": ["job_id"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        job_id = str(args.get("job_id", "")).strip()
        if not job_id:
            return "Error: missing job_id."
        action = args.get("action", "status")

        if action == "stop":
            resp = client.stop_process(cid, job_id)
            resp = resp if isinstance(resp, dict) else {}
            vm.audit("exec_command", cid, "Stop background process", {"job_id": job_id})
            if resp.get("ok"):
                return f"Job {job_id} stopped."
            return f"Could not stop job {job_id}: {resp.get('reason') or 'unknown'}."

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
        return f"{header}\n(no log yet)"
