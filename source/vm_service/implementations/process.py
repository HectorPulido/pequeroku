"""Lightweight background-process management over the cached SSH connection.

Each job is launched detached via ``setsid`` so it survives the request, writes
to a per-job log file, and records its PID. Status/stop reuse the same cached SSH
client, so every call is a fast, non-blocking SSH round-trip — the agent polls
across turns instead of holding a socket open for a long-running command.

Job artifacts live under ``/app/.pequenin/jobs/<job_id>.{log,pid,cmd}``.
"""

from __future__ import annotations

import re
import shlex
import uuid

import paramiko

from models import VMRecord
from .ssh_cache import exec_and_close
from .ssh_pool import borrow

JOBS_DIR = "/app/.pequenin/jobs"

# Upper bound for a server-side `wait` so a status call can never outlive the
# SSH/HTTP read timeout (the client widens its HTTP timeout to wait + margin).
_MAX_WAIT_SECONDS = 240


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


def _read_pid_file(vm: VMRecord, pidf: str) -> int | None:
    """Best-effort recovery of a launched job's PID from its ``.pid`` file.

    Used when the launch round-trip raised or returned no PID: the job is
    detached with ``setsid``, so it can be RUNNING even though we lost its stdout
    (SSH-pool contention under a burst of tool calls is the usual cause). A fresh
    round-trip reads the pid the launcher wrote. Returns the PID if the file
    exists and names a number, else ``None``. Never raises.
    """
    try:
        with borrow(vm) as conn:
            out, _ = _run(conn.cli, f"cat {shlex.quote(pidf)} 2>/dev/null")
    except Exception:
        return None
    tokens = out.strip().split()
    if tokens and tokens[-1].isdigit():
        return int(tokens[-1])
    return None


def start_process(vm: VMRecord, command: str, cwd: str = "/app") -> dict[str, object]:
    job_id = _new_job_id()
    log = f"{JOBS_DIR}/{job_id}.log"
    pidf = f"{JOBS_DIR}/{job_id}.pid"
    cmdf = f"{JOBS_DIR}/{job_id}.cmd"

    # Write the command to a script file via SFTP to avoid all shell-quoting
    # issues with the (possibly multi-line) user command.
    script = f"#!/usr/bin/env bash\ncd {shlex.quote(cwd)}\n{command}\n"
    launch = (
        f"cd {shlex.quote(cwd)} && "
        f"setsid bash {shlex.quote(cmdf)} > {shlex.quote(log)} 2>&1 < /dev/null & "
        f"PID=$!; echo $PID > {shlex.quote(pidf)}; echo $PID"
    )

    out = ""
    launched = False
    try:
        with borrow(vm) as conn:
            cli, sftp = conn.cli, conn.sftp
            _run(cli, f"mkdir -p {shlex.quote(JOBS_DIR)}")
            # pyrefly: ignore  # missing-attribute
            with sftp.file(cmdf, "w") as f:
                f.write(script)
            out, _err = _run(cli, launch)
            launched = True
    except Exception as e:
        # The launch round-trip itself failed. Because the job is detached, it may
        # ALREADY be running (the failure can hit after fork, while reading stdout).
        # Recover its PID from the pid file before declaring failure — otherwise the
        # caller relaunches and a second `apt-get`/`pip` collides on the dpkg lock.
        pid = _read_pid_file(vm, pidf)
        if pid is not None:
            return {"ok": True, "job_id": job_id, "pid": pid, "log_path": log, "reason": ""}
        return {
            "ok": False,
            "job_id": job_id,
            "pid": None,
            "log_path": log,
            "reason": f"Process error: {e}",
        }

    pid: int | None = None
    tokens = out.strip().split()
    if tokens and tokens[-1].isdigit():
        pid = int(tokens[-1])
    # Launch ran but the PID echo was lost (slow flush / truncated read). The job is
    # detached and almost certainly up; recover from the pid file so a transient read
    # glitch doesn't masquerade as a launch failure and trigger a duplicate run.
    if pid is None and launched:
        pid = _read_pid_file(vm, pidf)

    return {
        "ok": pid is not None,
        "job_id": job_id,
        "pid": pid,
        "log_path": log,
        "reason": "" if pid is not None else "Could not start process",
    }


def process_status(
    vm: VMRecord,
    job_id: str,
    lines: int = 80,
    since_bytes: int | None = None,
    wait: int = 0,
) -> dict[str, object]:
    job_id = _safe_job_id(job_id)
    log = f"{JOBS_DIR}/{job_id}.log"
    pidf = f"{JOBS_DIR}/{job_id}.pid"
    qlog = shlex.quote(log)
    qpid = shlex.quote(pidf)

    # Optional server-side wait: block (polling the pid every 2s) until the job
    # exits or `wait` seconds elapse, so the caller makes ONE round-trip instead of
    # hammering status in a tight loop. Bounded so it can't outlive the SSH/HTTP
    # read timeout.
    wait = max(0, min(int(wait or 0), _MAX_WAIT_SECONDS))
    wait_block = ""
    if wait > 0:
        wait_block = (
            f'PID=$(cat {qpid} 2>/dev/null); '
            f'if [ -n "$PID" ]; then i=0; '
            f'while [ "$i" -lt {wait} ]; do kill -0 "$PID" 2>/dev/null || break; '
            f'sleep 2; i=$((i+2)); done; fi; '
        )

    # Log slice: a byte offset (delta polling) when since_bytes is given, else the
    # trailing `lines`. SIZE is the current total so the caller can use it as the
    # next since_bytes and only ever receive NEW output.
    if since_bytes is not None and int(since_bytes) >= 0:
        log_slice = f"tail -c +{int(since_bytes) + 1} {qlog} 2>/dev/null || true"
    else:
        log_slice = f"tail -n {int(lines)} {qlog} 2>/dev/null || true"

    cmd = (
        f"{wait_block}"
        f"if [ -f {qpid} ]; then PID=$(cat {qpid}); "
        f'if kill -0 "$PID" 2>/dev/null; then echo "STATUS running $PID"; '
        f'else echo "STATUS exited $PID"; fi; '
        f"else echo 'STATUS unknown 0'; fi; "
        f"SZ=$(wc -c < {qlog} 2>/dev/null || echo 0); echo \"SIZE $SZ\"; "
        f"echo '---LOG---'; {log_slice}"
    )
    # The exec timeout must outlast the wait loop.
    with borrow(vm) as conn:
        out, _ = _run(conn.cli, cmd, timeout=wait + 15)

    status = "unknown"
    pid: int | None = None
    log_size = 0
    head, _sep, tail = out.partition("---LOG---")
    for line in head.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0] == "STATUS":
            if parts[1] in ("running", "exited", "unknown"):
                status = parts[1]
            if parts[2].isdigit() and int(parts[2]) > 0:
                pid = int(parts[2])
        elif len(parts) >= 2 and parts[0] == "SIZE" and parts[1].isdigit():
            log_size = int(parts[1])

    return {
        "ok": True,
        "job_id": job_id,
        "status": status,
        "pid": pid,
        "log": tail.strip("\n"),
        "log_size": log_size,
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
