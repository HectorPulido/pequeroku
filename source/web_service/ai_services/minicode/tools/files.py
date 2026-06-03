"""Herramientas de archivos sobre la VM: read, write, edit, glob, grep.

Adaptación Pequeroku: en vez del filesystem local, todo se hace contra la VM del
usuario vía ``VMServiceClient`` (read_file / upload_files / list_dirs / search).
La cascada de estrategias de matching de ``edit`` (exact → flexible → block-anchor)
se conserva tal cual de minicode: es pura y muy valiosa para que el ``oldString``
del modelo encaje aunque no copie el whitespace exacto.
"""
from __future__ import annotations

import difflib
import fnmatch
import posixpath
import re

from vm_manager.vm_client import SearchRequest, VMFile, VMPaths, VMUploadFiles

from .base import Tool, ToolContext, truncate
from . import vm

DEFAULT_READ_LIMIT = 2000
MAX_LINE_CHARS = 2000
GLOB_DEEP_DEPTH = 12
GLOB_SHALLOW_DEPTH = 4


# --------------------------------------------------------------------------- #
# helpers de VM
# --------------------------------------------------------------------------- #
def _read_file(client, cid: str, path: str) -> dict:
    """``read_file`` de la VM → dict {name, content, length, found}."""
    resp = client.read_file(cid, path)
    return resp if isinstance(resp, dict) else {}


def _write_file(client, cid: str, path: str, content: str) -> None:
    """Escribe (crea/sobrescribe) un archivo de texto en la VM."""
    client.upload_files(
        cid,
        VMUploadFiles(
            dest_path="/",
            clean=False,
            files=[VMFile(path=path, text=content)],
        ),
    )


def _list_dir(client, cid: str, path: str, depth: int = 1) -> list[dict]:
    resp = client.list_dirs(cid, VMPaths(paths=[path], depth=depth))
    return [e for e in resp if isinstance(e, dict)] if isinstance(resp, list) else []


def _similar(client, cid: str, path: str) -> list[str]:
    parent = posixpath.dirname(path) or "/"
    name = posixpath.basename(path)
    try:
        entries = _list_dir(client, cid, parent, depth=1)
        names = [e.get("name", "") for e in entries]
        return difflib.get_close_matches(name, names, n=3)
    except Exception:
        return []


def _mini_diff(old: str, new: str) -> str:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1)
    lines = list(diff)[2:]  # quita las cabeceras ---/+++
    return "\n".join(lines[:40])


# --------------------------------------------------------------------------- #
# edit: cascada de estrategias de matching (sin cambios respecto a minicode)
# --------------------------------------------------------------------------- #
class EditError(Exception):
    pass


def _exact(content: str, old: str) -> list[tuple[int, int]]:
    out, start = [], content.find(old)
    while start != -1:
        out.append((start, start + len(old)))
        start = content.find(old, start + 1)
    return out


def _flexible(content: str, old: str) -> list[tuple[int, int]]:
    """Tolera diferencias de whitespace/indentación: cada bloque de espacios de
    ``old`` se convierte en ``\\s+`` y el resto se escapa."""
    parts = [p for p in re.split(r"(\s+)", old) if p != ""]
    if not parts:
        return []
    pattern = "".join(r"\s+" if p.isspace() else re.escape(p) for p in parts)
    try:
        return [(m.start(), m.end()) for m in re.finditer(pattern, content)]
    except re.error:
        return []


def _block_anchor(content: str, old: str) -> list[tuple[int, int]]:
    """Último recurso: ancla primera y última línea del bloque (>=3 líneas)."""
    old_lines = old.split("\n")
    if len(old_lines) < 3:
        return []
    first = old_lines[0].strip()
    last = next((l.strip() for l in reversed(old_lines) if l.strip()), "")
    if not first or not last:
        return []
    clines = content.split("\n")
    offsets = [0]
    for l in clines:
        offsets.append(offsets[-1] + len(l) + 1)
    out: list[tuple[int, int]] = []
    for i, line in enumerate(clines):
        if line.strip() != first:
            continue
        for j in range(i + 1, len(clines)):
            if clines[j].strip() == last:
                out.append((offsets[i], offsets[j] + len(clines[j])))
                break
    return out


def apply_edit(content: str, old: str, new: str, replace_all: bool = False) -> str:
    for strategy in (_exact, _flexible, _block_anchor):
        matches = strategy(content, old)
        if not matches:
            continue
        if replace_all:
            result = content
            for s, e in sorted(matches, reverse=True):
                result = result[:s] + new + result[e:]
            return result
        if len(matches) > 1:
            raise EditError(
                f"oldString aparece {len(matches)} veces; añade más contexto "
                "alrededor para que sea único (o usa replaceAll)."
            )
        s, e = matches[0]
        return content[:s] + new + content[e:]
    raise EditError(
        "No se encontró oldString en el archivo; debe coincidir con el contenido "
        "(se toleran diferencias de espacios)."
    )


# --------------------------------------------------------------------------- #
# herramientas
# --------------------------------------------------------------------------- #
class ReadTool(Tool):
    name = "read"
    read_only = True
    description = (
        "Read a file from the VM workspace. Returns numbered lines. Use offset/limit "
        "to paginate large files. Detects directories, binaries and missing files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {"type": "string", "description": "Path to the file (absolute or relative to /app)."},
            "offset": {"type": "integer", "description": "1-indexed line to start from."},
            "limit": {"type": "integer", "description": "Max lines to read (default 2000)."},
        },
        "required": ["filePath"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, args["filePath"])
        resp = _read_file(client, cid, path)

        if not resp.get("found"):
            # Puede ser un directorio o no existir: intentamos listarlo.
            entries = _list_dir(client, cid, path, depth=1)
            real = [e for e in entries if e.get("path") != path]
            if real:
                vm.audit("read_file", cid, "List directory", {"path": path})
                names = sorted(
                    e.get("name", "") + ("/" if e.get("path_type") == "directory" else "")
                    for e in real
                )
                return f"Directorio {path}:\n" + "\n".join(names[:200])
            sims = _similar(client, cid, path)
            hint = f" ¿Quisiste decir: {', '.join(sims)}?" if sims else ""
            vm.audit("read_file", cid, "Read file (missing)", {"path": path}, success=False)
            return f"Error: no existe el archivo {path}.{hint}"

        content = resp.get("content") or ""
        if "\x00" in content[:1024]:
            return f"Error: archivo binario, no se puede leer como texto: {path}"

        offset = max(int(args.get("offset", 1) or 1), 1)
        limit = int(args.get("limit", DEFAULT_READ_LIMIT) or DEFAULT_READ_LIMIT)
        lines = content.split("\n")
        chunk = lines[offset - 1 : offset - 1 + limit]
        out = []
        for i, line in enumerate(chunk, start=offset):
            if len(line) > MAX_LINE_CHARS:
                line = line[:MAX_LINE_CHARS] + "… (línea truncada)"
            out.append(f"{i:>6}\t{line}")
        result = "\n".join(out)
        if offset - 1 + limit < len(lines):
            result += f"\n\n[el archivo tiene {len(lines)} líneas; continúa con offset={offset + limit}]"
        vm.audit("read_file", cid, "Read file", {"path": path})
        return result or "(archivo vacío)"


class WriteTool(Tool):
    name = "write"
    description = (
        "Write content to a file in the VM, creating it (and any parent directories) "
        "or overwriting it completely. Use `edit` for small targeted changes instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {"type": "string", "description": "Path to the file."},
            "content": {"type": "string", "description": "Full file content."},
        },
        "required": ["filePath", "content"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, args["filePath"])
        content = args["content"]
        _write_file(client, cid, path, content)
        vm.audit("create_file", cid, "File created", {"path": path})
        return f"Escrito {path} ({len(content.splitlines())} líneas)."


class EditTool(Tool):
    name = "edit"
    description = (
        "Replace oldString with newString in a file in the VM. oldString must match "
        "the file (whitespace differences are tolerated) and be unique unless "
        "replaceAll is true. If oldString is empty, the file is created with newString."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {"type": "string", "description": "File to modify."},
            "oldString": {"type": "string", "description": "Text to replace (empty = create file)."},
            "newString": {"type": "string", "description": "Replacement text (must differ from oldString)."},
            "replaceAll": {"type": "boolean", "description": "Replace all occurrences."},
        },
        "required": ["filePath", "oldString", "newString"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        path = vm.resolve(ctx, args["filePath"])
        old = args.get("oldString", "")
        new = args["newString"]
        if old == new:
            return "Error: oldString y newString son idénticos."
        if old == "":
            _write_file(client, cid, path, new)
            vm.audit("create_file", cid, "File created (edit)", {"path": path})
            return f"Creado {path}."

        resp = _read_file(client, cid, path)
        if not resp.get("found"):
            return f"Error: no existe el archivo {path}."
        content = resp.get("content") or ""
        try:
            updated = apply_edit(content, old, new, bool(args.get("replaceAll")))
        except EditError as e:
            return f"Error: {e}"
        _write_file(client, cid, path, updated)
        vm.audit("create_file", cid, "File edited", {"path": path})
        diff = _mini_diff(content, updated)
        return f"Editado {path}.\n{diff}" if diff else f"Editado {path}."


class GlobTool(Tool):
    name = "glob"
    read_only = True
    description = (
        "Find files matching a glob pattern (e.g. src/**/*.py) in the VM. Returns up "
        "to 100 paths. Use grep to search file contents instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern."},
            "path": {"type": "string", "description": "Root directory (default: /app)."},
        },
        "required": ["pattern"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        pattern = args["pattern"]
        root = vm.resolve(ctx, args.get("path") or ctx.config.workdir)
        depth = GLOB_DEEP_DEPTH if "**" in pattern else GLOB_SHALLOW_DEPTH
        entries = _list_dir(client, cid, root, depth=depth)

        matches: list[str] = []
        for e in entries:
            if e.get("path_type") != "file":
                continue
            p = e.get("path", "")
            target = vm.relpath(p, root) if "/" in pattern else e.get("name", "")
            if fnmatch.fnmatch(target, pattern):
                matches.append(p)
        matches.sort()
        if not matches:
            return "No se encontraron archivos."
        vm.audit("read_workspace", cid, "Glob", {"pattern": pattern, "root": root})
        shown = matches[:100]
        out = "\n".join(shown)
        if len(matches) > 100:
            out += f"\n\n[mostrando 100 de {len(matches)}; usa un patrón más específico]"
        return out


class GrepTool(Tool):
    name = "grep"
    read_only = True
    description = (
        "Search file contents in the VM with a text/regex pattern (grep). Returns "
        "matches as path: line. Optionally filter files with an include glob (e.g. *.py)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Text or regex pattern."},
            "path": {"type": "string", "description": "Directory to search (default: /app)."},
            "include": {"type": "string", "description": "Glob filter for files (e.g. *.py)."},
        },
        "required": ["pattern"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        client, cid = vm.get_client(ctx)
        pattern = args["pattern"]
        root = vm.resolve(ctx, args.get("path") or ctx.config.workdir)
        include = args.get("include")
        req = SearchRequest(
            pattern=pattern,
            root=root,
            case_insensitive=False,
            include_globs=[include] if include else [],
            max_results_total=250,
            timeout_seconds=10,
        ).apply_exclude_diff()
        resp = client.search(cid, req)
        hits = resp if isinstance(resp, list) else []

        lines: list[str] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            path = hit.get("path", "")
            for m in hit.get("matchs", []) or []:
                lines.append(f"{path}: {str(m)[:200]}")
        vm.audit("search", cid, "Grep", {"pattern": pattern, "root": root})
        return truncate("\n".join(lines)) if lines else "Sin coincidencias."
