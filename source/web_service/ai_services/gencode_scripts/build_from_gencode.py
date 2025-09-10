#!/usr/bin/env python3
"""
gencode.py

Reads 'gencode.txt', extracts the YAML that appears AFTER the last
'---HERE-YAML--' marker (even if it's wrapped in ``` / ```yaml / ```yml fences),
parses it, generates files with the specified path/mode/text, and then deletes
both 'gencode.txt' and this script itself.

Designed for Debian. Requires PyYAML; if not present, the script will attempt
to install it automatically via pip.
"""

import os
import re
import stat
import sys
import subprocess
from pathlib import Path

# ----------------------------- Helpers --------------------------------- #


def ensure_pyyaml():
    """Ensure PyYAML is available; attempt to install if missing."""
    try:
        import yaml  # noqa: F401

        return
    except ImportError:
        print("[info] PyYAML not found. Attempting to install 'pyyaml'...", flush=True)
        # Try to install for the current interpreter
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
        except subprocess.CalledProcessError as e:
            print(
                f"[error] Failed to install PyYAML automatically: {e}", file=sys.stderr
            )
            print("Please install it manually: pip install pyyaml", file=sys.stderr)
            sys.exit(1)


def read_gencode_txt(path: Path) -> str:
    """Read the entire gencode.txt file."""
    if not path.exists():
        print(f"[error] '{path}' not found.", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def extract_yaml_blob(full_text: str) -> str:
    """
    Extract the YAML that appears AFTER the last '---HERE-YAML--'.
    If the YAML is wrapped in code fences (``` / ```yaml / ```yml), strip them.
    """
    marker = "---HERE-YAML--"
    idx = full_text.rfind(marker)
    if idx == -1:
        print(
            "[error] Marker '---HERE-YAML--' not found in gencode.txt.", file=sys.stderr
        )
        sys.exit(1)

    yaml_candidate = full_text[idx + len(marker) :].strip()

    # If wrapped in triple backticks, strip the opening line and the closing fence.
    # Matches: ``` , ```yaml , ```yml  (case-insensitive)
    fence_open_re = re.compile(r"^\s*```(?:\s*|yaml|yml)\s*\n", re.IGNORECASE)
    fence_close_re = re.compile(r"\n\s*```\s*$")

    if fence_open_re.search(yaml_candidate) and fence_close_re.search(yaml_candidate):
        yaml_candidate = fence_open_re.sub("", yaml_candidate, count=1)
        yaml_candidate = fence_close_re.sub("", yaml_candidate, count=1)

    # Also handle single-line fenced blocks (edge case)
    single_line_fence = re.compile(
        r"^\s*```(?:\s*|yaml|yml)\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL
    )
    m = single_line_fence.match(yaml_candidate)
    if m:
        yaml_candidate = m.group(1).strip()

    if not yaml_candidate:
        print("[error] YAML content after marker is empty.", file=sys.stderr)
        sys.exit(1)

    return yaml_candidate


def parse_yaml(yaml_text: str) -> dict:
    """Parse YAML text into a Python dict using PyYAML."""
    import yaml  # ensured by ensure_pyyaml()

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        print(f"[error] Failed to parse YAML: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("[error] Top-level YAML is not a mapping/object.", file=sys.stderr)
        sys.exit(1)
    if "files" not in data or not isinstance(data["files"], list):
        print("[error] YAML must contain a 'files' list.", file=sys.stderr)
        sys.exit(1)
    return data


def write_files(files_spec: list):
    """
    For each file spec with keys:
      - path: file path
      - mode: string like "0644" (octal)
      - text: file content
    Create directories, write content, and chmod accordingly.
    """
    for i, spec in enumerate(files_spec, start=1):
        if not isinstance(spec, dict):
            print(f"[error] File spec #{i} is not a mapping/object.", file=sys.stderr)
            sys.exit(1)

        path = spec.get("path")
        mode_str = spec.get("mode")
        text = spec.get("text", "")

        if not path or not isinstance(path, str):
            print(f"[error] File spec #{i} missing valid 'path'.", file=sys.stderr)
            sys.exit(1)
        if not mode_str or not isinstance(mode_str, str):
            print(
                f"[error] File spec #{i} missing valid 'mode' (string like '0644').",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            file_mode = int(mode_str, 8)  # interpret as octal, e.g. "0644"
        except ValueError:
            print(
                f"[error] File spec #{i} has invalid mode '{mode_str}'. Use octal string like '0644'.",
                file=sys.stderr,
            )
            sys.exit(1)

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

        # Apply permissions. Keep file type bits intact; only set permission bits.
        os.chmod(
            out_path, file_mode | stat.S_IFREG if out_path.is_file() else file_mode
        )

        print(f"[ok] Wrote: {out_path} (mode {mode_str})")


def self_delete_and_cleanup(gencode_txt: Path, self_path: Path):
    """Remove gencode.txt and this script itself."""
    # Remove gencode.txt
    try:
        if gencode_txt.exists():
            gencode_txt.unlink()
            print(f"[ok] Deleted: {gencode_txt}")
        else:
            print(f"[warn] '{gencode_txt}' not found during cleanup.")
    except Exception as e:
        print(f"[warn] Failed to delete '{gencode_txt}': {e}", file=sys.stderr)

    # Remove this script
    try:
        if self_path.exists():
            # On some systems, removing a running script is permitted.
            self_path.unlink()
            print(f"[ok] Deleted: {self_path}")
        else:
            print(f"[warn] '{self_path}' not found during self-delete.")
    except Exception as e:
        print(f"[warn] Failed to delete '{self_path}': {e}", file=sys.stderr)


# ------------------------------ Main ----------------------------------- #


def main():
    ensure_pyyaml()

    gencode_txt = Path("gencode.txt").resolve()
    self_path = Path(__file__).resolve()

    full_text = read_gencode_txt(gencode_txt)
    yaml_blob = extract_yaml_blob(full_text)
    data = parse_yaml(yaml_blob)

    files_spec = data.get("files", [])
    write_files(files_spec)

    # Final cleanup
    self_delete_and_cleanup(gencode_txt, self_path)


if __name__ == "__main__":
    main()
