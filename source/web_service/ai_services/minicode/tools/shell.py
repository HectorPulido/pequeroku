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

import re
import shlex
import time

from .base import Tool, ToolContext, truncate
from . import vm

# Foreground timeout ceiling: the VMServiceClient HTTP call cuts off at 30s, so we
# leave margin. For anything longer or a service → background=true.
MAX_FOREGROUND_SECONDS = 25

# Commands that reliably outrun the foreground cap (dependency installs, full
# upgrades, compiles). Run in the foreground they just burn a ~25-35s timeout and
# push the agent into fragile foreground retries; we auto-promote them to a
# background job instead. Conservative on purpose: only well-known install/build
# verbs, matched on the actual command (not its arguments).
_LONG_RUNNING_RE = re.compile(
    r"""(?:^|[\s;&|(/])          # start, a shell separator, or a path '/' before the verb
    (?:
        (?:apt-get|apt|aptitude)(?:\s+\S+){0,6}?\s+(?:install|upgrade|full-upgrade|dist-upgrade|build-dep)\b
      | (?:pip|pip3)\s+install
      | python3?\s+-m\s+pip\s+install
      | (?:npm|pnpm|yarn)\s+(?:install|ci|add)\b
      | (?:poetry|pipenv)\s+install
      | (?:cargo|go)\s+(?:build|install)
      | (?:gradlew?|mvn)\b
      | docker\s+build
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _looks_long_running(command: str) -> bool:
    return bool(_LONG_RUNNING_RE.search(command or ""))


# --------------------------------------------------------------------------- #
# Per-turn state stashed on the Config: background jobs launched this turn (so a
# guard can tell when a destructive command targets a still-running job) and the
# last-seen log byte offset per job (so status polls return only NEW output).
# --------------------------------------------------------------------------- #
def _jobs(ctx: ToolContext) -> dict:
    jobs = getattr(ctx.config, "_bg_jobs", None)
    if jobs is None:
        jobs = {}
        try:
            ctx.config._bg_jobs = jobs
        except Exception:
            pass
    return jobs


def _offsets(ctx: ToolContext) -> dict:
    offs = getattr(ctx.config, "_job_log_offsets", None)
    if offs is None:
        offs = {}
        try:
            ctx.config._job_log_offsets = offs
        except Exception:
            pass
    return offs


# Absolute paths whose recursive deletion is never legitimate here.
_DANGEROUS_RM_TARGETS = {"/", "/app", "/root", "/home", "~", "$HOME", "/*"}

# apt packages that pull enormous desktop/TeX/Java stacks (e.g. python3-matplotlib
# → texlive + openjdk + ffmpeg). In this PaaS VM the right move is a venv + pip.
_HEAVY_APT_RE = re.compile(
    r"\bapt(?:-get)?\b[^\n]*?\binstall\b[^\n]*?\b("
    r"python3-(?:matplotlib|scipy|wordcloud|pyqt5|opencv|pandas|"
    r"sklearn|scikit-learn|sympy)"
    r"|texlive\S*|openjdk\S*"
    r")\b",
    re.IGNORECASE,
)


def _recursive_rm_targets(command: str):
    """If ``command`` runs a recursive ``rm``, return its target paths; else None.

    Used to refuse deleting a directory a running job is writing into (the move
    that corrupts a venv mid-install). Splits on shell separators so it also
    catches `... && rm -rf x`."""
    targets: list[str] = []
    found = False
    for seg in re.split(r"[;&|]+", command or ""):
        toks = seg.strip().split()
        if "rm" not in toks:
            continue
        toks = toks[toks.index("rm") :]
        flags = "".join(
            t[1:] for t in toks[1:] if t.startswith("-") and not t.startswith("--")
        )
        recursive = "r" in flags.lower() or "--recursive" in toks[1:]
        if not recursive:
            continue
        found = True
        targets.extend(t for t in toks[1:] if not t.startswith("-"))
    return targets if found else None


def _norm_target(t: str) -> str:
    t = (t or "").strip().strip('"').strip("'")
    return t.rstrip("/") or "/"


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
        "and KEEPS RUNNING after this turn. Check it or stop it with the `process` tool.\n"
        "Known long installs/builds (apt-get install, pip install, npm install, "
        "cargo/go build, ...) are auto-promoted to a background job even without "
        "background=true, so they don't time out; poll them with `process`."
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

        blocked = self._guard(command, ctx, client, cid)
        if blocked:
            return blocked

        run_cmd = self._in_workdir(args, ctx, command)

        if args.get("background"):
            return self._run_background(client, cid, run_cmd, command, ctx)

        # Auto-promote known long installs/builds to a background job: foreground
        # they would hit the ~25-35s cap and time out, which is exactly what pushes
        # the agent into foreground retries (and duplicate apt → dpkg lock fights).
        # An explicit `timeout` means the caller deliberately wants it foreground.
        if not args.get("timeout") and _looks_long_running(command):
            note = self._run_background(client, cid, run_cmd, command, ctx)
            return (
                "Note: this looks like a long install/build, so it was started in "
                "the BACKGROUND (foreground would time out). Poll it with `process` "
                "until status=exited, then read the log to confirm it succeeded.\n"
                + note
            )

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
    def _guard(self, command: str, ctx: ToolContext, client, cid: str) -> str | None:
        """Refuse a few destructive moves that have wrecked real runs. Returns an
        explanatory message to send back instead of running, or None to proceed."""
        targets = _recursive_rm_targets(command)
        if targets is not None:
            for t in targets:
                if _norm_target(t) in _DANGEROUS_RM_TARGETS or t in _DANGEROUS_RM_TARGETS:
                    return (
                        f"Refused: `rm -rf {t}` targets a critical path and would wipe "
                        "the workspace/home. If you meant a specific subfolder, delete "
                        "that exact path instead."
                    )
            # Don't delete a directory a background job we launched is still writing
            # into — that is exactly what corrupts a venv mid-install.
            for jid, jcmd in list(_jobs(ctx).items()):
                if not any(_norm_target(t) and _norm_target(t) in jcmd for t in targets):
                    continue
                try:
                    st = client.process_status(cid, jid, lines=1)
                    running = isinstance(st, dict) and st.get("status") == "running"
                except Exception:
                    running = False
                if running:
                    return (
                        f'Refused: background job_id="{jid}" is still writing under '
                        f"that path; deleting it now would corrupt its work (this is how "
                        f"a venv gets wrecked mid-install). Stop it first "
                        f'(process(job_id="{jid}", action="stop")) or wait for it '
                        f'(process(job_id="{jid}", action="wait")), then retry.'
                    )
        if _HEAVY_APT_RE.search(command or ""):
            return (
                "Refused: installing that via apt pulls a huge GUI/TeX/Java stack "
                "(hundreds of packages, ~1GB). For Python libraries use a venv + pip "
                "instead: `python3 -m venv /app/.venv && /app/.venv/bin/pip install "
                "<lib>`. If you truly need the system package, install it alone and "
                "deliberately (and expect the size)."
            )
        return None

    # ------------------------------------------------------------------ #
    def _run_background(
        self, client, cid: str, run_cmd: str, command: str, ctx: ToolContext | None = None
    ) -> str:
        resp = client.start_process(cid, run_cmd)
        resp = resp if isinstance(resp, dict) else {}
        if not resp.get("ok"):
            reason = resp.get("reason") or "could not start process"
            failed_job = resp.get("job_id", "")
            vm.audit(
                "exec_command",
                cid,
                "Start background process",
                {"command": command},
                success=False,
            )
            msg = f"Error launching in background: {reason}"
            # The launch is detached: a transient error here does NOT guarantee the
            # process never started. Before relaunching (a duplicate apt/pip would
            # collide on the dpkg lock), confirm with process(status) on this job_id.
            if failed_job:
                msg += (
                    f'\nThis MAY still be running as job_id="{failed_job}". '
                    f'Check with process(job_id="{failed_job}", action="status") '
                    f"BEFORE you launch it again."
                )
            return msg

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
            # Seed the delta offset so the first process(status) poll returns only
            # output produced AFTER this launch snapshot, not the whole log again.
            if ctx is not None:
                _offsets(ctx)[job_id] = int(st.get("log_size", 0) or 0)
        except Exception:
            pass

        # Remember the job (this turn) so a later destructive command can tell it is
        # still in use before nuking its directory.
        if ctx is not None and job_id:
            _jobs(ctx)[job_id] = command

        vm.audit(
            "exec_command",
            cid,
            "Start background process",
            {"command": command, "job_id": job_id},
        )
        msg = (
            f"Started in background. job_id={job_id} pid={pid} status={status}.\n"
            f"Log: {log_path}\n"
            f'WAIT for it (one call, blocks until it finishes): '
            f'process(job_id="{job_id}", action="wait")  ·  '
            f'Peek without blocking: process(job_id="{job_id}", action="status")  ·  '
            f'Stop: process(job_id="{job_id}", action="stop")'
        )
        if log.strip():
            msg += f"\n--- first output ---\n{truncate(log, from_tail=True)}"
        return msg


class ProcessTool(Tool):
    name = "process"
    description = (
        "Inspect, WAIT FOR, or stop a background job started by bash(background=true).\n"
        "- action='wait' (PREFERRED for installs/builds): blocks SERVER-SIDE until the "
        "job finishes (or up to `wait` seconds, default 120, max 240), then returns its "
        "final status and any new output. Use this instead of polling `status` in a "
        "loop — one call, not fifteen. If it returns still 'running', just call wait "
        "again.\n"
        "- action='status': a NON-blocking peek — returns whether it is running plus "
        "only the output that is NEW since your last check (no need to re-read the whole "
        "log).\n"
        "- action='stop': terminates it (SIGTERM to its process group).\n"
        "Do NOT call status repeatedly in a tight loop; it wastes tokens. Wait instead."
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
                "enum": ["wait", "status", "stop"],
                "description": "What to do (default: status). Prefer 'wait' for installs/builds.",
            },
            "wait": {
                "type": "integer",
                "description": "For action='wait': max seconds to block (default 120, max 240).",
            },
            "lines": {
                "type": "integer",
                "description": "Trailing log lines on the FIRST status of a job (default 80); "
                "later checks return only new output regardless.",
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
            _jobs(ctx).pop(job_id, None)
            if resp.get("ok"):
                return f"Job {job_id} stopped."
            return f"Could not stop job {job_id}: {resp.get('reason') or 'unknown'}."

        lines = int(args.get("lines", 80) or 80)
        offsets = _offsets(ctx)
        since = offsets.get(job_id)  # None on the first check → server returns the tail

        wait_secs = 0
        if action == "wait":
            wait_secs = int(args.get("wait", 120) or 120)
            wait_secs = max(1, min(wait_secs, 240))

        resp = client.process_status(
            cid, job_id, lines=lines, since_bytes=since, wait=wait_secs
        )
        resp = resp if isinstance(resp, dict) else {}
        status = resp.get("status", "unknown")
        pid = resp.get("pid")
        log = resp.get("log", "")
        # Advance the offset so the NEXT check returns only output after this one.
        try:
            offsets[job_id] = int(resp.get("log_size", since or 0) or 0)
        except Exception:
            pass
        if status == "exited":
            _jobs(ctx).pop(job_id, None)

        vm.audit("exec_command", cid, "Background process status", {"job_id": job_id})
        header = f"job_id={job_id} status={status} pid={pid}"
        if log.strip():
            label = "log" if since is None else "new output"
            return f"{header}\n--- {label} ---\n{truncate(log, from_tail=True)}"
        if since is not None:
            return f"{header}\n(no new output since last check)"
        return f"{header}\n(no log yet)"
