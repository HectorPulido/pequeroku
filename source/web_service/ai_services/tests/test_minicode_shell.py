"""Tests for the shell tools (ai_services/minicode/tools/shell.py): the destructive
guards, auto-promotion of long installs to background, background launch failure,
and the process(status/wait/stop) delta-offset bookkeeping.

The roundtrip happy paths live in test_minicode.py; this file targets the
guard/background/process branches.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_services.minicode.config import Config
from ai_services.minicode.session import Session
from ai_services.minicode.tools.base import ToolContext
from ai_services.minicode.tools import shell as sh


class FakeVMClient:
    def __init__(self):
        self.exec_resp = {"ok": True, "stdout": "out\n", "stderr": "", "reason": ""}
        self.start_resp = {
            "ok": True,
            "job_id": "j1",
            "pid": 42,
            "log_path": "/app/.pequeroku/jobs/j1.log",
            "reason": "",
        }
        self.status_resp = {
            "ok": True,
            "job_id": "j1",
            "status": "running",
            "pid": 42,
            "log": "server up\n",
            "log_size": 10,
            "reason": "",
        }
        self.stop_resp = {"ok": True, "job_id": "j1", "status": "stopped", "reason": ""}
        self.calls = []

    def execute_sh(self, cid, command, timeout=None):
        self.calls.append(("exec", command, timeout))
        return self.exec_resp

    def start_process(self, cid, command):
        self.calls.append(("start", command))
        return self.start_resp

    def process_status(self, cid, job_id, lines=80, since_bytes=None, wait=0):
        self.calls.append(("status", job_id, since_bytes, wait))
        return self.status_resp

    def stop_process(self, cid, job_id):
        self.calls.append(("stop", job_id))
        return self.stop_resp


def make_ctx(client):
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = client
    return ToolContext(
        config=config, session=Session(), spawn_subagent=lambda *a: iter(())
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(sh.time, "sleep", lambda *_: None)


# --------------------------------------------------------------------------- #
# _looks_long_running / _recursive_rm_targets pure helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cmd",
    [
        "pip install flask",
        "apt-get install -y curl",
        "npm install",
        "cargo build",
        "docker build .",
    ],
)
def test_looks_long_running_true(cmd):
    assert sh._looks_long_running(cmd)


def test_looks_long_running_false():
    assert not sh._looks_long_running("echo hi")
    assert not sh._looks_long_running("ls -la")


def test_recursive_rm_targets():
    assert sh._recursive_rm_targets("rm -rf /app/x") == ["/app/x"]
    assert sh._recursive_rm_targets("echo hi && rm -r build") == ["build"]
    assert sh._recursive_rm_targets("rm file.txt") is None  # not recursive
    assert sh._recursive_rm_targets("ls") is None


# --------------------------------------------------------------------------- #
# foreground
# --------------------------------------------------------------------------- #
def test_bash_foreground_failure_suggests_background():
    client = FakeVMClient()
    client.exec_resp = {"ok": False, "reason": "timed out"}
    out = sh.BashTool().execute({"command": "sleep 99"}, make_ctx(client))
    assert "Error: timed out" in out and "background=true" in out


def test_bash_explicit_timeout_stays_foreground():
    client = FakeVMClient()
    # Long-running verb BUT an explicit timeout -> caller wants foreground.
    sh.BashTool().execute(
        {"command": "pip install x", "timeout": 5000}, make_ctx(client)
    )
    assert client.calls[0][0] == "exec"  # not promoted to background


# --------------------------------------------------------------------------- #
# auto-promotion to background
# --------------------------------------------------------------------------- #
def test_bash_autopromotes_long_running_to_background():
    client = FakeVMClient()
    out = sh.BashTool().execute({"command": "pip install flask"}, make_ctx(client))
    assert any(c[0] == "start" for c in client.calls)
    assert "long install/build" in out and "job_id=j1" in out


def test_bash_explicit_background():
    client = FakeVMClient()
    out = sh.BashTool().execute(
        {"command": "python3 server.py", "background": True}, make_ctx(client)
    )
    assert any(c[0] == "start" for c in client.calls)
    assert "Started in background" in out and "first output" in out  # log was non-empty


def test_bash_background_launch_failure():
    client = FakeVMClient()
    client.start_resp = {"ok": False, "reason": "no slots", "job_id": "j9"}
    out = sh.BashTool().execute(
        {"command": "python3 server.py", "background": True}, make_ctx(client)
    )
    assert "Error launching in background: no slots" in out
    assert 'job_id="j9"' in out and "BEFORE you launch it again" in out


# --------------------------------------------------------------------------- #
# destructive guards
# --------------------------------------------------------------------------- #
def test_guard_refuses_dangerous_rm():
    client = FakeVMClient()
    out = sh.BashTool().execute({"command": "rm -rf /app"}, make_ctx(client))
    assert out.startswith("Refused:") and "critical path" in out
    assert client.calls == []  # never executed


def test_guard_refuses_heavy_apt():
    client = FakeVMClient()
    out = sh.BashTool().execute(
        {"command": "apt-get install -y texlive-full"}, make_ctx(client)
    )
    assert "Refused:" in out and "venv + pip" in out
    assert client.calls == []


def test_guard_refuses_rm_of_running_job_dir():
    client = FakeVMClient()
    ctx = make_ctx(client)
    # A background job (this turn) is writing under /app/.venv and is still running.
    ctx.config._bg_jobs = {"j1": "python3 -m pip install -r reqs.txt under /app/.venv"}
    out = sh.BashTool().execute({"command": "rm -rf /app/.venv"}, ctx)
    assert "Refused:" in out and 'job_id="j1"' in out
    # the only client call was the status check, never the rm
    assert all(c[0] != "exec" for c in client.calls)


# --------------------------------------------------------------------------- #
# ProcessTool
# --------------------------------------------------------------------------- #
def test_process_missing_job_id():
    out = sh.ProcessTool().execute({"job_id": ""}, make_ctx(FakeVMClient()))
    assert out == "Error: missing job_id."


def test_process_stop_success_and_failure():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = sh.ProcessTool().execute({"job_id": "j1", "action": "stop"}, ctx)
    assert out == "Job j1 stopped."

    client.stop_resp = {"ok": False, "reason": "already gone"}
    out = sh.ProcessTool().execute({"job_id": "j1", "action": "stop"}, ctx)
    assert "Could not stop job j1" in out and "already gone" in out


def test_process_status_first_then_delta():
    client = FakeVMClient()
    ctx = make_ctx(client)
    # First check: no offset yet -> server returns the tail, labelled "log".
    out1 = sh.ProcessTool().execute({"job_id": "j1", "action": "status"}, ctx)
    assert "status=running" in out1 and "--- log ---" in out1 and "server up" in out1
    # First status call had since_bytes=None; offset is now seeded to log_size (10).
    assert client.calls[0] == ("status", "j1", None, 0)

    # Second check: offset is set; no new output -> "(no new output...)".
    client.status_resp = {
        "ok": True,
        "status": "running",
        "pid": 42,
        "log": "",
        "log_size": 10,
    }
    out2 = sh.ProcessTool().execute({"job_id": "j1", "action": "status"}, ctx)
    assert "(no new output since last check)" in out2
    assert client.calls[1] == ("status", "j1", 10, 0)


def test_process_wait_widens_and_blocks():
    client = FakeVMClient()
    out = sh.ProcessTool().execute(
        {"job_id": "j1", "action": "wait", "wait": 300}, make_ctx(client)
    )
    # wait clamped to 240 and passed to process_status
    assert client.calls[0] == ("status", "j1", None, 240)
    assert "status=running" in out


def test_process_exited_drops_job_from_registry():
    client = FakeVMClient()
    client.status_resp = {
        "ok": True,
        "status": "exited",
        "pid": 42,
        "log": "done\n",
        "log_size": 5,
    }
    ctx = make_ctx(client)
    ctx.config._bg_jobs = {"j1": "python3 server.py"}
    out = sh.ProcessTool().execute({"job_id": "j1", "action": "status"}, ctx)
    assert "status=exited" in out
    assert "j1" not in ctx.config._bg_jobs  # popped on exit
