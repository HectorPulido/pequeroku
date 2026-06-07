"""Tests for the minicode extensibility tier: skills, custom tools, project doc,
config loading and the small generator tools (skill/todo/task).

All VM I/O goes through an in-memory ``FakeVMClient`` (a dict path->content acting
as the VM filesystem), mirroring ``test_minicode.py``. No network, no DB: the audit
calls are best-effort and swallow the "DB access not allowed" RuntimeError.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ai_services.minicode.config import Config, load_dotenv
from ai_services.minicode.session import Session
from ai_services.minicode.tools.base import ToolContext
from ai_services.minicode import skills as skills_mod
from ai_services.minicode import custom_tools as ct_mod
from ai_services.minicode import project as project_mod
from ai_services.minicode.tools.skill import SkillTool
from ai_services.minicode.tools.todo import TodoWriteTool
from ai_services.minicode.tools.task import TaskTool
from ai_services.minicode.events import TodosUpdated


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeVMClient:
    """In-memory VM: a dict path->content. ``exec_ok`` toggles execute_sh result."""

    def __init__(self, exec_ok: bool = True) -> None:
        self.fs: dict[str, str] = {}
        self.exec_ok = exec_ok
        self.exec_calls: list[str] = []
        self.fail_read = False
        self.fail_list = False

    @staticmethod
    def _under(path: str, root: str) -> bool:
        return path == root or path.startswith(root.rstrip("/") + "/")

    def read_file(self, cid, path):
        if self.fail_read:
            raise RuntimeError("boom read")
        found = path in self.fs
        return {
            "name": path.rsplit("/", 1)[-1],
            "content": self.fs.get(path, ""),
            "found": found,
        }

    def list_dirs(self, cid, paths):
        if self.fail_list:
            raise RuntimeError("boom list")
        root = paths.paths[0]
        out = []
        for p in self.fs:
            if self._under(p, root) and p != root:
                out.append(
                    {"path": p, "name": p.rsplit("/", 1)[-1], "path_type": "file"}
                )
        return out

    def execute_sh(self, cid, command, timeout=None):
        self.exec_calls.append(command)
        if self.exec_ok:
            return {"ok": True, "stdout": "out\n", "stderr": "err\n", "reason": ""}
        return {"ok": False, "stdout": "", "stderr": "", "reason": "exit 1"}


def make_config(client: FakeVMClient | None = None) -> Config:
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    if client is None:
        config.container = None
    else:
        config.container = SimpleNamespace(container_id="vm-1", node=object())
        config._vm_client = client
    return config


def make_ctx(client: FakeVMClient, config: Config | None = None) -> ToolContext:
    config = config or make_config(client)
    return ToolContext(
        config=config, session=Session(), spawn_subagent=lambda *a: iter(())
    )


def drive(gen):
    """Run a generator tool to completion, returning (events, return_value)."""
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        return events, stop.value


# --------------------------------------------------------------------------- #
# skills.py — frontmatter parsing
# --------------------------------------------------------------------------- #
def test_parse_frontmatter_reads_top_level_keys_and_ignores_nested():
    text = (
        "---\n"
        "name: my-skill\n"
        'description: "does a thing"\n'
        "metadata:\n"
        "  nested: ignored\n"
        "---\n"
        "Body line 1\nBody line 2"
    )
    meta, body = skills_mod._parse_frontmatter(text)
    # Only top-level keys are read; the nested "  nested: ignored" line is skipped.
    assert meta["name"] == "my-skill"
    assert meta["description"] == "does a thing"
    assert "nested" not in meta
    assert body == "Body line 1\nBody line 2"


def test_parse_frontmatter_no_frontmatter():
    assert skills_mod._parse_frontmatter("just a body") == ({}, "just a body")


def test_parse_frontmatter_unterminated_block_is_not_frontmatter():
    text = "---\nname: x\nno closing fence"
    assert skills_mod._parse_frontmatter(text) == ({}, text)


# --------------------------------------------------------------------------- #
# skills.py — builtin skills (shipped product files)
# --------------------------------------------------------------------------- #
def test_load_builtin_skills_returns_shipped_skills():
    skills_mod._builtin_cache = None  # bust cache for a clean read
    builtins = skills_mod._load_builtin_skills()
    names = {s.name for s in builtins}
    # The 4 builtin skills shipped under minicode/builtin_skills/
    assert {"authoring-mcp", "authoring-skills", "authoring-tools"} <= names
    for s in builtins:
        assert s.source == "builtin"
        assert s.body  # body is preloaded for builtins
        assert s.path == f"builtin:{s.name}"


def test_load_builtin_skills_is_cached():
    skills_mod._builtin_cache = None
    first = skills_mod._load_builtin_skills()
    second = skills_mod._load_builtin_skills()
    assert first is second  # second call returns the cached list object


# --------------------------------------------------------------------------- #
# skills.py — discovery
# --------------------------------------------------------------------------- #
def test_discover_skills_without_container_returns_only_builtins():
    config = make_config(None)
    found = skills_mod.discover_skills(config)
    assert found  # builtins are always present
    assert all(s.source == "builtin" for s in found)


def test_discover_skills_includes_valid_project_skill():
    client = FakeVMClient()
    client.fs[
        "/app/.pequenin/skills/deploy/SKILL.md"
    ] = "---\nname: deploy\ndescription: Deploy the app\n---\nRun deploy steps."
    config = make_config(client)
    found = {s.name: s for s in skills_mod.discover_skills(config)}
    assert "deploy" in found
    assert found["deploy"].source == "project"
    assert found["deploy"].base_dir == "/app/.pequenin/skills/deploy"


def test_discover_skills_project_overrides_builtin():
    client = FakeVMClient()
    # Same name as a builtin -> the project skill must win.
    client.fs[
        "/app/.pequenin/skills/authoring-skills/SKILL.md"
    ] = "---\nname: authoring-skills\ndescription: My override\n---\nOverridden."
    config = make_config(client)
    found = {s.name: s for s in skills_mod.discover_skills(config)}
    assert found["authoring-skills"].source == "project"
    assert found["authoring-skills"].description == "My override"


def test_discover_skills_skips_invalid_manifests():
    client = FakeVMClient()
    # name != folder
    client.fs[
        "/app/.pequenin/skills/folderA/SKILL.md"
    ] = "---\nname: not-folderA\ndescription: x\n---\nbody"
    # missing description
    client.fs["/app/.pequenin/skills/nodesc/SKILL.md"] = "---\nname: nodesc\n---\nbody"
    # bad name (uppercase)
    client.fs[
        "/app/.pequenin/skills/BadName/SKILL.md"
    ] = "---\nname: BadName\ndescription: x\n---\nbody"
    config = make_config(client)
    names = {s.name for s in skills_mod.discover_skills(config)}
    assert (
        "not-folderA" not in names and "nodesc" not in names and "BadName" not in names
    )


def test_discover_skills_survives_vm_list_error():
    client = FakeVMClient()
    client.fail_list = True
    config = make_config(client)
    found = skills_mod.discover_skills(config)
    assert found and all(s.source == "builtin" for s in found)


# --------------------------------------------------------------------------- #
# skills.py — index block + body loading
# --------------------------------------------------------------------------- #
def test_skills_index_block_empty_is_empty_string():
    assert skills_mod.skills_index_block([]) == ""


def test_skills_index_block_escapes_and_lists():
    skill = skills_mod.Skill(
        name="deploy", description="a & b <x>", path="builtin:deploy", base_dir=""
    )
    block = skills_mod.skills_index_block([skill])
    assert "<available_skills>" in block and "</available_skills>" in block
    assert "<name>deploy</name>" in block
    assert "a &amp; b &lt;x&gt;" in block  # XML-escaped


def test_load_skill_body_unknown_skill():
    config = make_config(None)
    config.skills = []
    out = skills_mod.load_skill_body(config, "ghost")
    assert "unknown skill 'ghost'" in out


def test_load_skill_body_builtin_returns_wrapped_body():
    config = make_config(None)
    config.skills = [
        skills_mod.Skill(
            name="x",
            description="d",
            path="builtin:x",
            base_dir="",
            source="builtin",
            body="THE BODY",
        )
    ]
    out = skills_mod.load_skill_body(config, "x")
    assert '<skill_content name="x">' in out
    assert "THE BODY" in out
    assert "<skill_files>" not in out  # builtins are self-contained


def test_load_skill_body_project_reads_vm_and_lists_files():
    client = FakeVMClient()
    client.fs[
        "/app/.pequenin/skills/deploy/SKILL.md"
    ] = "---\nname: deploy\ndescription: d\n---\nBODY TEXT"
    client.fs["/app/.pequenin/skills/deploy/scripts/run.sh"] = "echo hi"
    config = make_config(client)
    config.skills = [
        skills_mod.Skill(
            name="deploy",
            description="d",
            path="/app/.pequenin/skills/deploy/SKILL.md",
            base_dir="/app/.pequenin/skills/deploy",
        )
    ]
    out = skills_mod.load_skill_body(config, "deploy")
    assert "BODY TEXT" in out
    assert "<skill_files>" in out
    assert "/app/.pequenin/skills/deploy/scripts/run.sh" in out


def test_load_skill_body_project_no_container():
    config = make_config(None)
    config.skills = [
        skills_mod.Skill(
            name="deploy", description="d", path="/p/SKILL.md", base_dir="/p"
        )
    ]
    assert "no VM is bound" in skills_mod.load_skill_body(config, "deploy")


# --------------------------------------------------------------------------- #
# custom_tools.py — schema normalization
# --------------------------------------------------------------------------- #
def test_normalize_schema_non_dict():
    assert ct_mod._normalize_schema("nope") == {"type": "object", "properties": {}}


def test_normalize_schema_forces_object_and_properties():
    out = ct_mod._normalize_schema({"required": ["x"]})
    assert out["type"] == "object" and out["properties"] == {}
    assert out["required"] == ["x"]


# --------------------------------------------------------------------------- #
# custom_tools.py — CustomTool.execute
# --------------------------------------------------------------------------- #
def test_custom_tool_execute_success_returns_combined_output():
    client = FakeVMClient(exec_ok=True)
    ctx = make_ctx(client)
    tool = ct_mod.CustomTool(
        "run-linter",
        "desc",
        {"type": "object", "properties": {}},
        "python3 run.py",
        "/app/.pequenin/tools/run-linter",
    )
    out = tool.execute({"path": "src"}, ctx)
    assert "out" in out and "err" in out
    # args are base64'd onto stdin; the command runs cd'd into the tool dir
    cmd = client.exec_calls[0]
    assert "cd /app/.pequenin/tools/run-linter &&" in cmd
    assert "base64 -d | python3 run.py" in cmd


def test_custom_tool_execute_failure_returns_error_message():
    client = FakeVMClient(exec_ok=False)
    ctx = make_ctx(client)
    tool = ct_mod.CustomTool(
        "run-linter", "desc", {"type": "object", "properties": {}}, "cmd", "/app/t"
    )
    out = tool.execute({}, ctx)
    assert "failed" in out and "exit 1" in out


# --------------------------------------------------------------------------- #
# custom_tools.py — discovery
# --------------------------------------------------------------------------- #
def _manifest(name, command="python3 run.py", description="A tool", **extra):
    man = {"name": name, "description": description, "command": command}
    man.update(extra)
    return json.dumps(man)


def test_discover_custom_tools_without_container():
    assert ct_mod.discover_custom_tools(make_config(None)) == []


def test_discover_custom_tools_builds_valid_tool():
    client = FakeVMClient()
    client.fs["/app/.pequenin/tools/run-linter/tool.json"] = _manifest("run-linter")
    tools = ct_mod.discover_custom_tools(make_config(client))
    assert len(tools) == 1
    t = tools[0]
    assert isinstance(t, ct_mod.CustomTool)
    assert t.name == "run-linter" and t.read_only is False


def test_discover_custom_tools_skips_invalid():
    client = FakeVMClient()
    client.fs["/app/.pequenin/tools/bad-json/tool.json"] = "{not json"
    client.fs["/app/.pequenin/tools/mismatch/tool.json"] = _manifest("other-name")
    client.fs["/app/.pequenin/tools/nocmd/tool.json"] = _manifest("nocmd", command="")
    tools = ct_mod.discover_custom_tools(make_config(client))
    assert tools == []


def test_discover_custom_tools_survives_list_error():
    client = FakeVMClient()
    client.fail_list = True
    assert ct_mod.discover_custom_tools(make_config(client)) == []


# --------------------------------------------------------------------------- #
# project.py — AGENTS.md / CLAUDE.md loading
# --------------------------------------------------------------------------- #
def test_load_project_doc_without_container():
    assert project_mod.load_project_doc(make_config(None)) is None


def test_load_project_doc_reads_agents_md():
    client = FakeVMClient()
    client.fs["/app/AGENTS.md"] = "Project rules here."
    out = project_mod.load_project_doc(make_config(client))
    assert "Project rules here." in out
    assert "/app/AGENTS.md" in out  # header references the path


def test_load_project_doc_falls_back_to_claude_md():
    client = FakeVMClient()
    client.fs["/app/CLAUDE.md"] = "Claude rules."
    out = project_mod.load_project_doc(make_config(client))
    assert "Claude rules." in out and "/app/CLAUDE.md" in out


def test_load_project_doc_none_when_absent():
    assert project_mod.load_project_doc(make_config(FakeVMClient())) is None


def test_load_project_doc_truncates_large_file():
    client = FakeVMClient()
    client.fs["/app/AGENTS.md"] = "x" * (project_mod.MAX_DOC_CHARS + 100)
    out = project_mod.load_project_doc(make_config(client))
    assert "[instructions truncated]" in out


# --------------------------------------------------------------------------- #
# config.py — .env loader + from_env
# --------------------------------------------------------------------------- #
def test_load_dotenv_sets_without_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "FOO=bar\n"
        'QUOTED="quoted-val"\n'
        "noequalsline\n"
        "PRESET=fromfile\n"
    )
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.setenv("PRESET", "preexisting")
    load_dotenv(str(env))
    import os

    assert os.environ["FOO"] == "bar"
    assert os.environ["QUOTED"] == "quoted-val"
    assert os.environ["PRESET"] == "preexisting"  # setdefault does not override


def test_load_dotenv_missing_file_is_noop(tmp_path):
    load_dotenv(str(tmp_path / "does-not-exist.env"))  # must not raise


def test_config_from_env_reads_values(monkeypatch):
    monkeypatch.setattr("ai_services.minicode.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example/v1")
    monkeypatch.setenv("MINICODE_MODEL", "gpt-5")
    monkeypatch.setenv("MINICODE_MAX_STEPS", "7")
    monkeypatch.setenv("MINICODE_TEMPERATURE", "0.5")
    monkeypatch.setenv("MINICODE_MAX_TOKENS", "1234")
    monkeypatch.setenv("MINICODE_RESTRICT_WORKDIR", "true")
    cfg = Config.from_env()
    assert cfg.api_key == "secret"
    assert cfg.base_url == "https://example/v1"
    assert cfg.model == "gpt-5"
    assert cfg.max_steps == 7
    assert cfg.temperature == 0.5
    assert cfg.max_output_tokens == 1234
    assert cfg.restrict_to_workdir is True


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.setattr("ai_services.minicode.config.load_dotenv", lambda *a, **k: None)
    for key in (
        "OPENAI_API_KEY",
        "MINICODE_API_KEY",
        "OPENAI_BASE_URL",
        "MINICODE_BASE_URL",
        "MINICODE_MODEL",
        "OPENAI_MODEL",
        "MINICODE_TEMPERATURE",
        "MINICODE_MAX_TOKENS",
        "MINICODE_RESTRICT_WORKDIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MINICODE_MAX_STEPS", "50")
    cfg = Config.from_env()
    assert cfg.api_key == ""
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.model == "gpt-4o"
    assert cfg.temperature is None and cfg.max_output_tokens is None
    assert cfg.restrict_to_workdir is False


# --------------------------------------------------------------------------- #
# tools/skill.py
# --------------------------------------------------------------------------- #
def test_skill_tool_loads_builtin_body():
    config = make_config(None)
    config.skills = [
        skills_mod.Skill(
            name="x",
            description="d",
            path="builtin:x",
            base_dir="",
            source="builtin",
            body="LOADED",
        )
    ]
    ctx = make_ctx(FakeVMClient(), config=config)  # client present so audit path runs
    out = SkillTool().execute({"name": "x"}, ctx)
    assert "LOADED" in out


def test_skill_tool_unknown_skill_returns_error():
    config = make_config(None)
    config.skills = []
    ctx = ToolContext(
        config=config, session=Session(), spawn_subagent=lambda *a: iter(())
    )
    out = SkillTool().execute({"name": "ghost"}, ctx)
    assert "unknown skill 'ghost'" in out


# --------------------------------------------------------------------------- #
# tools/todo.py
# --------------------------------------------------------------------------- #
def test_todowrite_updates_session_and_renders():
    ctx = make_ctx(FakeVMClient())
    todos = [
        {"content": "do A", "status": "completed"},
        {"content": "do B", "status": "in_progress"},
        {"content": "do C", "status": "pending"},
    ]
    events, summary = drive(TodoWriteTool().execute({"todos": todos}, ctx))
    assert ctx.session.todos == todos
    assert any(isinstance(e, TodosUpdated) for e in events)
    assert "[x] do A" in summary and "[~] do B" in summary and "[ ] do C" in summary


def test_todowrite_handles_empty_list():
    ctx = make_ctx(FakeVMClient())
    _events, summary = drive(TodoWriteTool().execute({}, ctx))
    assert summary.startswith("Updated task list:")


# --------------------------------------------------------------------------- #
# tools/task.py
# --------------------------------------------------------------------------- #
def test_task_tool_delegates_and_wraps_report():
    captured = {}

    def spawn(agent_type, prompt):
        captured["type"] = agent_type
        captured["prompt"] = prompt
        yield "intermediate-event"
        return "the report"

    ctx = ToolContext(config=make_config(None), session=Session(), spawn_subagent=spawn)
    events, ret = drive(
        TaskTool().execute(
            {
                "description": "find x",
                "prompt": "do the thing",
                "subagent_type": "explore",
            },
            ctx,
        )
    )
    assert captured == {"type": "explore", "prompt": "do the thing"}
    assert "intermediate-event" in events
    assert ret == '<task subagent="explore">\nthe report\n</task>'


def test_task_tool_normalizes_unknown_subagent_type():
    def spawn(agent_type, prompt):
        yield from ()
        return f"ran-{agent_type}"

    ctx = ToolContext(config=make_config(None), session=Session(), spawn_subagent=spawn)
    _events, ret = drive(
        TaskTool().execute(
            {"description": "x", "prompt": "p", "subagent_type": "bogus"}, ctx
        )
    )
    assert 'subagent="general"' in ret  # invalid type falls back to general
