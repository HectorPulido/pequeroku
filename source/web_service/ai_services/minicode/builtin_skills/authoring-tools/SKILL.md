---
name: authoring-tools
description: Create a custom tool for this workspace — a named, schema'd command that runs in the VM and the agent can call. Use when the user wants a reusable operation exposed as a first-class tool, or you spot a repeatable VM workflow worth wrapping.
---

# Authoring a custom tool

A custom tool turns a command into a first-class tool the agent can call by name,
with a typed argument schema — unlike a one-off `bash` call. It runs INSIDE this VM
(the same sandbox `bash` uses), so it grants no new powers; it just packages a
workflow cleanly.

## Where custom tools live

    /app/.pequenin/tools/<name>/
    ├── tool.json        # the manifest (required)
    └── <your script>    # whatever `command` runs (run.py, run.sh, ...)

One folder per tool. Bundle any helper files in the same folder.

## tool.json

    {
      "name": "run-linter",
      "description": "Run ruff on a path and return the findings. Use before committing Python.",
      "parameters": {
        "type": "object",
        "properties": { "path": { "type": "string", "description": "File or dir to lint." } },
        "required": ["path"]
      },
      "command": "python3 run.py"
    }

Fields:
- `name` — REQUIRED. Lowercase letters/digits with single hyphens
  (`^[a-z0-9]+(-[a-z0-9]+)*$`), 1–64 chars, and it MUST equal the folder name.
- `description` — REQUIRED. Say WHEN to use the tool and what it returns — this is what
  the agent reads to decide whether to call it.
- `parameters` — JSON Schema (an object) describing the arguments the agent passes.
  Defaults to `{"type":"object","properties":{}}` if omitted.
- `command` — REQUIRED. The command to run (e.g. `python3 run.py`, `bash run.sh`,
  `node run.js`). It runs with the tool's folder as the working directory.

## The contract: args in on STDIN, result out on STDOUT

When the agent calls the tool, your `command` runs in the tool's folder and receives
the validated arguments as a single JSON object on **stdin**. Whatever it writes to
stdout/stderr is returned to the agent. Example `run.py`:

    import json, subprocess, sys
    args = json.load(sys.stdin)            # e.g. {"path": "app/"}
    out = subprocess.run(["ruff", "check", args["path"]], capture_output=True, text=True)
    print(out.stdout or out.stderr)

## How to create one

1. Pick a kebab-case `<name>`.
2. `write` `/app/.pequenin/tools/<name>/tool.json` with the manifest above.
3. `write` the script your `command` runs, in the same folder.
4. The tool is discovered on the NEXT turn (discovery runs once, at turn start). It
   then appears in your toolset and you can call it by `name`.

## Limits and gotchas

- Runs FOREGROUND, ~25s cap (same as foreground `bash`). For long work, have the
  command background it itself (`setsid`, `nohup … &`) and return quickly.
- Runs with the agent's VM privileges (root in the sandbox) — same as `bash`. Don't
  put secrets in `tool.json`.
- `name` != folder, invalid JSON, or a missing `description`/`command` → the tool is
  silently skipped (check the next turn's toolset to confirm it loaded).
- Custom tools are VM files: they persist with the workspace but are wiped on a
  workspace reset.
- A custom tool can't shadow a built-in tool (the built-in wins on a name clash).
