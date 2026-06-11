"""Prompt strings for the MCP server, centralized for review.

`SERVER_INSTRUCTIONS` is handed to FastMCP and surfaced to the client in the MCP
``initialize`` response, so it is the one place that tells the connecting agent
what PequeRoku is, what a VM looks like, and how the tools fit together — context
it otherwise has no way to know. Tool-level descriptions stay as docstrings on
``server.py`` (FastMCP derives each tool's description from its docstring); keep
the two consistent.

Kept deliberately tight: this text is loaded once per session into the client's
context, so it is worth real budget but must not sprawl.
"""

from __future__ import annotations

# Mirrors the facts the in-app agent (ai_services/minicode/prompts.py) relies on,
# rewritten for an EXTERNAL MCP client — the client is the agent, PequeRoku is only
# the sandbox (never Pequenin). Update both if the VM environment changes.
SERVER_INSTRUCTIONS = """\
PequeRoku gives you hands on a sandbox: isolated Debian VMs you fully control. \
You are the agent; these tools are the body, not the brain. Anything you run \
happens inside one isolated VM (no access to other VMs or the host network), so \
the blast radius is that VM, never the user's machine.

# Two ways to run things — pick before you start
- One-shot (`run_code`): for "run this and tell me the result". PequeRoku boots a \
fresh VM, writes your files, runs the command, returns stdout/stderr/exit_code, \
then destroys the VM. No state survives. Best for tests, scripts, quick checks.
- Persistent (`get_or_create_container` → `container_exec`/`write_files`/...): for \
work that must survive across calls — a service you keep running, a repo you \
iterate on, a workspace to come back to. Reuse the same `name` to find it again.

# The VM environment
- OS is Debian. Prefer `python3`/`pip3` over `python`/`pip`.
- The working directory is `/app` — your primary workspace. `run_code` files and \
`write_files` (default dest) land there; put new projects under `/app`. Files in a \
persistent container's `/app` survive reboots.
- `container_exec` runs each command via a fresh shell; it does not keep a cwd or \
shell state between calls. `cd /app && ...` if you depend on the directory.

# Choosing a VM type (flavor)
Call `list_types` FIRST to see the flavors your API key may use, each with its \
vCPUs / memory / disk and its credit cost. The `type` argument on `run_code` and \
`get_or_create_container` accepts a type name (e.g. "small") or its numeric id. \
Omit `type` on `run_code` to default to the cheapest allowed type. \
Each running container/run holds credits equal to its type's cost; a \
`quota_exceeded` error means you must destroy something or pick a cheaper type.

# Exposing a web app / preview
To serve an app, bind it to `0.0.0.0` (not just 127.0.0.1) on a high, unprivileged \
port, and start it detached so the command returns — e.g. \
`container_exec(..., background=true)`, or `nohup ... &` / `setsid -f ...`. Then \
call `get_preview` to see which ports are listening and their preview paths. \
Long-running processes started with `background=true` return a `process_id` you \
poll with `process_status`.

# Conventions
- Tool outputs are truncated to keep your context bounded; a `truncated` flag tells \
you when there is more. Read files in chunks or write output to a file in the VM if \
you need the full content.
- `destroy_container` is irreversible and requires `confirm=true`.
- Your API key has scopes (read / exec / admin). A tool may return a \
`forbidden_scope` error if the key lacks the needed scope — that is a key-config \
issue, not something to retry.
"""


# --- prompt templates ------------------------------------------------------
# Registered as MCP prompts in ``server.py`` (the ``@mcp.prompt()`` functions).
# These are reusable, task-shaped starters a user invokes; each expands into a
# user message that bakes in the right PequeRoku workflow so the tools get used
# well. Parameters map to the prompt's arguments.

RUN_IN_SANDBOX = """\
Run the following in a throwaway PequeRoku VM and report the result. \
First call `list_types` if you need to pick a flavor; otherwise let `run_code` \
default to the cheapest. Put any source in `files` (paths resolve under `/app`), \
run it with `run_code`, then report stdout, stderr and the exit code. The VM is \
destroyed automatically — do not create a persistent container for this.

Task:
{task}"""

DEPLOY_WEB_APP = """\
Stand up this web app in a persistent PequeRoku container and give me a working \
preview. Steps:
1. `get_or_create_container` with a stable `name` (call `list_types` first if you \
need to choose a flavor with enough resources).
2. Write the project into `/app` with `write_files`, then install and build with \
`container_exec`.
3. Start the server in the background bound to `0.0.0.0` on a high port \
(`container_exec(..., background=true)`); keep the returned process_id.
4. Verify it is up with `process_status` and `get_preview`, then report the \
listening port(s) and preview path.
If something fails, read logs/files and fix it before reporting back.

App to deploy:
{app}"""

SETUP_WORKSPACE = """\
Get me a persistent PequeRoku workspace named "{name}" to work in across calls. \
Use `get_or_create_container` (call `list_types` first if it must be created and \
you need to choose a flavor). Then inspect `/app` with `read_path` and tell me \
what is already there and how the project runs (or that it is empty and ready). \
Leave the container running."""
