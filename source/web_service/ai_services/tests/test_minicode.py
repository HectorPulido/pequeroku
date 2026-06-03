"""Tests del motor minicode adaptado a Pequeroku.

Cubren: las tools VM-backed (read/write/edit/glob/grep/bash/process) contra un
``FakeVMClient`` en memoria, la auto-reparación del historial (``Session.sanitize``)
y un turno completo del bucle del agente con un LLM scripteado (sin red).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from ai_services.minicode.config import Config
from ai_services.minicode.session import Session
from ai_services.minicode.agent import Agent
from ai_services.minicode.events import (
    AssistantTextDelta,
    ToolCallStarted,
    ToolResult,
    Usage,
)
from ai_services.minicode.tools.base import ToolContext
from ai_services.minicode.tools import files as files_tools
from ai_services.minicode.tools import shell as shell_tools


# --------------------------------------------------------------------------- #
# Dobles de prueba
# --------------------------------------------------------------------------- #
class FakeVMClient:
    """VMServiceClient en memoria: un dict path->content como "filesystem"."""

    def __init__(self) -> None:
        self.fs: dict[str, str] = {}
        self.started: list[str] = []
        self.stopped: list[str] = []

    @staticmethod
    def _under(path: str, root: str) -> bool:
        return path == root or path.startswith(root.rstrip("/") + "/")

    def read_file(self, cid, path):
        found = path in self.fs
        return {
            "name": path.rsplit("/", 1)[-1],
            "content": self.fs.get(path, ""),
            "length": len(self.fs.get(path, "")),
            "found": found,
        }

    def upload_files(self, cid, payload):
        for f in payload.files:
            self.fs[f.path] = f.text or ""
        return {"ok": True}

    def list_dirs(self, cid, paths):
        root = paths.paths[0]
        out = []
        for p in self.fs:
            if self._under(p, root) and p != root:
                out.append({"path": p, "name": p.rsplit("/", 1)[-1], "path_type": "file"})
        return out

    def search(self, cid, req):
        hits = []
        for p, content in self.fs.items():
            if not self._under(p, req.root):
                continue
            matchs = [ln for ln in content.splitlines() if req.pattern in ln]
            if matchs:
                hits.append({"path": p, "matchs": matchs})
        return hits

    def execute_sh(self, cid, command, timeout=None):
        return {"ok": True, "stdout": f"ran:{command}\n", "stderr": "", "reason": ""}

    def start_process(self, cid, command):
        self.started.append(command)
        return {
            "ok": True,
            "job_id": "job1",
            "pid": 4242,
            "log_path": "/app/.pequeroku/jobs/job1.log",
            "reason": "",
        }

    def process_status(self, cid, job_id, lines=80):
        return {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "pid": 4242,
            "log": "server up\n",
            "reason": "",
        }

    def stop_process(self, cid, job_id):
        self.stopped.append(job_id)
        return {"ok": True, "job_id": job_id, "status": "stopped", "reason": ""}


def make_ctx(client: FakeVMClient) -> ToolContext:
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = client  # get_client usa el cliente cacheado, no construye uno real
    return ToolContext(config=config, session=Session(), spawn_subagent=lambda *a: iter(()))


# --------------------------------------------------------------------------- #
# Tools de archivos
# --------------------------------------------------------------------------- #
def test_write_then_read_roundtrip():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = files_tools.WriteTool().execute({"filePath": "src/app.py", "content": "hello\nworld"}, ctx)
    assert "/app/src/app.py" in out
    assert client.fs["/app/src/app.py"] == "hello\nworld"

    read = files_tools.ReadTool().execute({"filePath": "src/app.py"}, ctx)
    assert "hello" in read and "world" in read


def test_edit_replaces_unique_snippet():
    client = FakeVMClient()
    client.fs["/app/a.txt"] = "alpha\nbeta\ngamma"
    ctx = make_ctx(client)
    out = files_tools.EditTool().execute(
        {"filePath": "a.txt", "oldString": "beta", "newString": "BETA"}, ctx
    )
    assert "Editado" in out
    assert client.fs["/app/a.txt"] == "alpha\nBETA\ngamma"


def test_edit_create_when_old_empty():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = files_tools.EditTool().execute(
        {"filePath": "new.txt", "oldString": "", "newString": "content"}, ctx
    )
    assert "Creado" in out
    assert client.fs["/app/new.txt"] == "content"


def test_glob_matches_by_name():
    client = FakeVMClient()
    client.fs.update(
        {"/app/main.py": "x", "/app/src/a.py": "y", "/app/notes.txt": "z"}
    )
    ctx = make_ctx(client)
    out = files_tools.GlobTool().execute({"pattern": "*.py"}, ctx)
    assert "/app/main.py" in out and "/app/src/a.py" in out
    assert "/app/notes.txt" not in out


def test_grep_returns_matches():
    client = FakeVMClient()
    client.fs["/app/todo.py"] = "x = 1\n# TODO: fix this\ny = 2"
    ctx = make_ctx(client)
    out = files_tools.GrepTool().execute({"pattern": "TODO"}, ctx)
    assert "/app/todo.py" in out and "TODO" in out


# --------------------------------------------------------------------------- #
# Tools de shell
# --------------------------------------------------------------------------- #
def test_bash_foreground():
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = shell_tools.BashTool().execute({"command": "echo hi"}, ctx)
    assert "ran:echo hi" in out


def test_bash_background_survives_via_start_process(monkeypatch):
    monkeypatch.setattr(shell_tools.time, "sleep", lambda *_: None)
    client = FakeVMClient()
    ctx = make_ctx(client)
    out = shell_tools.BashTool().execute(
        {"command": "python3 main.py", "background": True}, ctx
    )
    assert client.started == ["python3 main.py"]
    assert "job1" in out and "status=running" in out


def test_process_status_and_stop():
    client = FakeVMClient()
    ctx = make_ctx(client)
    status = shell_tools.ProcessTool().execute({"job_id": "job1", "action": "status"}, ctx)
    assert "status=running" in status and "server up" in status

    stop = shell_tools.ProcessTool().execute({"job_id": "job1", "action": "stop"}, ctx)
    assert "detenido" in stop and client.stopped == ["job1"]


# --------------------------------------------------------------------------- #
# Resiliencia del historial
# --------------------------------------------------------------------------- #
def test_session_sanitize_repairs_dangling_tool_calls():
    s = Session()
    s.messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
            ],
        },
        # falta el mensaje tool para c1 (historial roto)
        {"role": "tool", "tool_call_id": "orphan", "content": "huérfano"},
    ]
    s.sanitize()
    # se inserta un tool de relleno para c1 y se descarta el huérfano
    tool_msgs = [m for m in s.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "c1"


# --------------------------------------------------------------------------- #
# Bucle del agente (con LLM scripteado, sin red)
# --------------------------------------------------------------------------- #
class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def stream(self, messages, tools):
        msg = self.script[self.calls]
        self.calls += 1
        content = msg.get("content") or ""
        if content:
            from ai_services.minicode.events import AssistantTextStart, AssistantTextEnd

            yield AssistantTextStart()
            yield AssistantTextDelta(text=content)
            yield AssistantTextEnd()
        return msg


def test_agent_loop_executes_tool_then_answers():
    client = FakeVMClient()
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = client

    llm = FakeLLM(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "write",
                        "arguments": json.dumps({"filePath": "hello.txt", "content": "hi"}),
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
            {
                "content": "Listo, escribí hello.txt.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        ]
    )

    session = Session()
    session.add_user("crea hello.txt con 'hi'")
    events = list(Agent(config, llm, session=session).run())

    # la tool se ejecutó contra la VM fake
    assert client.fs["/app/hello.txt"] == "hi"
    # se emitieron los eventos esperados
    assert any(isinstance(e, ToolCallStarted) and e.name == "write" for e in events)
    assert any(isinstance(e, ToolResult) for e in events)
    assert any(isinstance(e, Usage) for e in events)
    # respuesta final del agente
    assert session.last_assistant_text() == "Listo, escribí hello.txt."
