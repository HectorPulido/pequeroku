"""Lightweight background-process management over the cached SSH connection.

Each job is launched detached via ``setsid`` so it survives the request, writes
to a per-job log file, and records its PID. Status/stop reuse the same cached SSH
client, so every call is a fast, non-blocking SSH round-trip — the agent polls
across turns instead of holding a socket open for a long-running command.

Job artifacts live under ``/app/.pequeroku/jobs/<job_id>.{log,pid,cmd}``.
"""

from __future__ import annotations

import re
import shlex
import uuid

import paramiko

from models import VMRecord
from .ssh_cache import exec_and_close
from .ssh_pool import borrow

JOBS_DIR = "/app/.pequeroku/jobs"


def _new_job_id() -> str:
    return uuid.uuid4().hex[:16]


def _safe_job_id(job_id: str) -> str:
    """Sanitize a client-supplied job id to a safe filename token."""
    return re.sub(r"[^A-Za-z0-9_-]", "", job_id or "")[:64]


def _run(cli: paramiko.SSHClient, command: str, timeout: int = 15) -> tuple[str, str]:
    out_b, err_b = exec_and_close(cli, command, timeout)
    return (
        out_b.decode("utf-8", errors="replace"),
        err_b.decode("utf-8", errors="replace"),
    )


def start_process(vm: VMRecord, command: str, cwd: str = "/app") -> dict[str, object]:
    job_id = _new_job_id()
    log = f"{JOBS_DIR}/{job_id}.log"
    pidf = f"{JOBS_DIR}/{job_id}.pid"
    cmdf = f"{JOBS_DIR}/{job_id}.cmd"

    with borrow(vm) as conn:
        cli, sftp = conn.cli, conn.sftp

        _run(cli, f"mkdir -p {shlex.quote(JOBS_DIR)}")

        # Write the command to a script file via SFTP to avoid all shell-quoting
        # issues with the (possibly multi-line) user command.
        script = f"#!/usr/bin/env bash\ncd {shlex.quote(cwd)}\n{command}\n"
        try:
            # pyrefly: ignore  # missing-attribute
            with sftp.file(cmdf, "w") as f:
                f.write(script)
        except Exception as e:
            return {
                "ok": False,
                "job_id": job_id,
                "pid": None,
                "log_path": log,
                "reason": f"Could not write command file: {e}",
            }

        launch = (
            f"cd {shlex.quote(cwd)} && "
            f"setsid bash {shlex.quote(cmdf)} > {shlex.quote(log)} 2>&1 < /dev/null & "
            f"PID=$!; echo $PID > {shlex.quote(pidf)}; echo $PID"
        )
        out, err = _run(cli, launch)

    pid: int | None = None
    tokens = out.strip().split()
    if tokens and tokens[-1].isdigit():
        pid = int(tokens[-1])

    return {
        "ok": pid is not None,
        "job_id": job_id,
        "pid": pid,
        "log_path": log,
        "reason": "" if pid is not None else (err.strip() or "Could not start process"),
    }


def process_status(vm: VMRecord, job_id: str, lines: int = 80) -> dict[str, object]:
    job_id = _safe_job_id(job_id)
    log = f"{JOBS_DIR}/{job_id}.log"
    pidf = f"{JOBS_DIR}/{job_id}.pid"

    cmd = (
        f"if [ -f {shlex.quote(pidf)} ]; then PID=$(cat {shlex.quote(pidf)}); "
        f'if kill -0 "$PID" 2>/dev/null; then echo "STATUS running $PID"; '
        f'else echo "STATUS exited $PID"; fi; '
        f"else echo 'STATUS unknown 0'; fi; "
        f"echo '---LOG---'; "
        f"tail -n {int(lines)} {shlex.quote(log)} 2>/dev/null || true"
    )
    with borrow(vm) as conn:
        out, _ = _run(conn.cli, cmd)

    status = "unknown"
    pid: int | None = None
    head, _sep, tail = out.partition("---LOG---")
    parts = head.strip().split()
    if len(parts) >= 3 and parts[0] == "STATUS":
        if parts[1] in ("running", "exited", "unknown"):
            status = parts[1]
        if parts[2].isdigit() and int(parts[2]) > 0:
            pid = int(parts[2])

    return {
        "ok": True,
        "job_id": job_id,
        "status": status,
        "pid": pid,
        "log": tail.strip("\n"),
        "reason": "",
    }


def stop_process(vm: VMRecord, job_id: str) -> dict[str, object]:
    job_id = _safe_job_id(job_id)
    pidf = f"{JOBS_DIR}/{job_id}.pid"

    cmd = (
        f"if [ -f {shlex.quote(pidf)} ]; then PID=$(cat {shlex.quote(pidf)}); "
        f'kill -TERM -"$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null; '
        f"echo STOPPED; else echo NOJOB; fi"
    )
    with borrow(vm) as conn:
        out, _ = _run(conn.cli, cmd)
    ok = "STOPPED" in out
    return {
        "ok": ok,
        "job_id": job_id,
        "status": "stopped" if ok else "unknown",
        "reason": "" if ok else "No such job",
    }
