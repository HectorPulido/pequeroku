"""Tests for the file tools (ai_services/minicode/tools/files.py): the edit
matching-strategy cascade and the Read/Glob/Grep edge cases not covered by the
roundtrip tests in test_minicode.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_services.minicode.config import Config
from ai_services.minicode.session import Session
from ai_services.minicode.tools.base import ToolContext
from ai_services.minicode.tools import files as f


class FakeVMClient:
    def __init__(self):
        self.fs: dict[str, str] = {}
        self.dirs: dict[str, str] = {}  # path -> "directory"

    @staticmethod
    def _under(path, root):
        return path == root or path.startswith(root.rstrip("/") + "/")

    def read_file(self, cid, path):
        return {
            "name": path.rsplit("/", 1)[-1],
            "content": self.fs.get(path, ""),
            "length": len(self.fs.get(path, "")),
            "found": path in self.fs,
        }

    def upload_files(self, cid, payload):
        for vf in payload.files:
            self.fs[vf.path] = vf.text or ""
        return {"ok": True}

    def list_dirs(self, cid, paths):
        root = paths.paths[0]
        out = []
        for p in self.fs:
            if self._under(p, root) and p != root:
                out.append({"path": p, "name": p.rsplit("/", 1)[-1], "path_type": "file"})
        for p, _ in self.dirs.items():
            if self._under(p, root) and p != root:
                out.append({"path": p, "name": p.rsplit("/", 1)[-1], "path_type": "directory"})
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


def make_ctx(client):
    config = Config(api_key="k", base_url="u", model="m", workdir="/app")
    config.container = SimpleNamespace(container_id="vm-1", node=object())
    config._vm_client = client
    return ToolContext(config=config, session=Session(), spawn_subagent=lambda *a: iter(()))


# --------------------------------------------------------------------------- #
# apply_edit strategy cascade
# --------------------------------------------------------------------------- #
def test_apply_edit_flexible_tolerates_whitespace():
    content = "def  foo( ):\n    return 1"
    # oldString has single spaces where the file has different whitespace
    out = f.apply_edit(content, "def foo( ):", "def bar():")
    assert out.startswith("def bar():")


def test_apply_edit_block_anchor_multiline():
    content = "start\nmiddle A\nmiddle B\nend\ntrailer"
    old = "start\n<whatever>\nend"  # 3 lines: anchors on first/last line
    out = f.apply_edit(content, old, "REPLACED")
    assert "REPLACED" in out and "trailer" in out and "middle A" not in out


def test_apply_edit_replace_all():
    content = "x = 1\nx = 1\nx = 1"
    out = f.apply_edit(content, "x = 1", "y = 2", replace_all=True)
    assert out == "y = 2\ny = 2\ny = 2"


def test_apply_edit_multiple_matches_without_replace_all_raises():
    with pytest.raises(f.EditError, match="appears 2 times"):
        f.apply_edit("a\na", "a", "b")


def test_apply_edit_not_found_raises():
    with pytest.raises(f.EditError, match="not be found|was not found"):
        f.apply_edit("hello", "zzz", "qqq")


# --------------------------------------------------------------------------- #
# EditTool edge cases
# --------------------------------------------------------------------------- #
def test_edit_identical_strings_rejected():
    ctx = make_ctx(FakeVMClient())
    out = f.EditTool().execute(
        {"filePath": "a.txt", "oldString": "same", "newString": "same"}, ctx
    )
    assert "identical" in out


def test_edit_missing_file_reports_error():
    ctx = make_ctx(FakeVMClient())
    out = f.EditTool().execute(
        {"filePath": "ghost.txt", "oldString": "a", "newString": "b"}, ctx
    )
    assert "does not exist" in out


def test_edit_propagates_editerror_as_text():
    client = FakeVMClient()
    client.fs["/app/a.txt"] = "dup\ndup"
    ctx = make_ctx(client)
    out = f.EditTool().execute(
        {"filePath": "a.txt", "oldString": "dup", "newString": "x"}, ctx
    )
    assert "Error:" in out and "appears 2 times" in out


# --------------------------------------------------------------------------- #
# ReadTool edge cases
# --------------------------------------------------------------------------- #
def test_read_directory_listing_when_path_is_dir():
    client = FakeVMClient()
    client.fs["/app/pkg/a.py"] = "x"
    client.fs["/app/pkg/b.py"] = "y"
    ctx = make_ctx(client)
    out = f.ReadTool().execute({"filePath": "pkg"}, ctx)
    assert out.startswith("Directory /app/pkg:")
    assert "a.py" in out and "b.py" in out


def test_read_missing_file_suggests_similar():
    client = FakeVMClient()
    client.fs["/app/main.py"] = "x"
    ctx = make_ctx(client)
    out = f.ReadTool().execute({"filePath": "mian.py"}, ctx)  # typo
    assert "does not exist" in out and "Did you mean" in out and "main.py" in out


def test_read_binary_file_rejected():
    client = FakeVMClient()
    client.fs["/app/bin.dat"] = "abc\x00def"
    ctx = make_ctx(client)
    out = f.ReadTool().execute({"filePath": "bin.dat"}, ctx)
    assert "binary file" in out


def test_read_pagination_footer_and_offset():
    client = FakeVMClient()
    client.fs["/app/big.txt"] = "\n".join(f"line{i}" for i in range(1, 11))
    ctx = make_ctx(client)
    out = f.ReadTool().execute({"filePath": "big.txt", "offset": 1, "limit": 3}, ctx)
    assert "     1\tline1" in out
    assert "continue with offset=4" in out  # more lines remain


def test_read_long_line_truncated():
    client = FakeVMClient()
    client.fs["/app/wide.txt"] = "z" * (f.MAX_LINE_CHARS + 50)
    ctx = make_ctx(client)
    out = f.ReadTool().execute({"filePath": "wide.txt"}, ctx)
    assert "(line truncated)" in out


def test_read_offset_beyond_eof_returns_empty_marker():
    client = FakeVMClient()
    client.fs["/app/one.txt"] = "only line"
    ctx = make_ctx(client)
    # offset past the end -> no lines selected -> "(empty file)" fallback
    out = f.ReadTool().execute({"filePath": "one.txt", "offset": 100}, ctx)
    assert out == "(empty file)"


# --------------------------------------------------------------------------- #
# GlobTool / GrepTool edge cases
# --------------------------------------------------------------------------- #
def test_glob_no_matches():
    client = FakeVMClient()
    client.fs["/app/a.py"] = "x"
    ctx = make_ctx(client)
    assert f.GlobTool().execute({"pattern": "*.rs"}, ctx) == "No files found."


def test_glob_with_path_separator_matches_relpath():
    client = FakeVMClient()
    client.fs["/app/src/deep/x.py"] = "x"
    ctx = make_ctx(client)
    out = f.GlobTool().execute({"pattern": "src/**/*.py"}, ctx)
    assert "/app/src/deep/x.py" in out


def test_grep_no_matches():
    client = FakeVMClient()
    client.fs["/app/a.py"] = "nothing here"
    ctx = make_ctx(client)
    assert f.GrepTool().execute({"pattern": "ZZZ"}, ctx) == "No matches."


def test_grep_returns_path_and_line():
    client = FakeVMClient()
    client.fs["/app/a.py"] = "alpha\nTODO: x\nbeta"
    ctx = make_ctx(client)
    out = f.GrepTool().execute({"pattern": "TODO", "include": "*.py"}, ctx)
    assert "/app/a.py: TODO: x" in out
