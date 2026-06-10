# Pequenin — Pequeroku's AI assistant

This document explains, end to end, how Pequeroku's AI system works: the
**Pequenin** assistant, an autonomous coding agent that operates the user's VM
(read/edit files, run commands, bring services up) from a chat inside the IDE.

> Audience: anyone about to touch the agent, the consumer, the tools or the VM
> access layer. File paths are relative to `source/`.


## 1. Overview

Three services collaborate:

| Service | Stack | Role |
|---|---|---|
| **web_service** | Django + DRF + Channels, served with `gunicorn -k uvicorn.workers.UvicornWorker -w 8`. Postgres + Redis. | App/API, auth, quotas, the **AI chat** (WebSocket) and the agent engine (`minicode`). System of record. |
| **vm_service** | FastAPI (a single uvicorn process). Redis-backed store, bearer auth. | VM lifecycle (QEMU) and **VM access over SSH** (files, exec, terminal, search, background processes). |
| **User VM** | Debian (qcow2 overlay on top of a golden). | The user's sandbox; the workspace lives in `/app`. |

The "brain" (LLM + agentic loop) runs inside web_service; the "hands"
(files/exec) are HTTP→SSH calls to vm_service, which executes them inside the
VM. The front end (React) only talks to web_service.

```
Browser (React, AiAssistantPanel)
   │  WebSocket  /ws/ai/<container_pk>/
   ▼
web_service · AIConsumer (Channels)         ── auth, quota, conversations, streaming
   │  run_pipeline(...)                         (ai_services/ai_consumers.py)
   ▼
minicode · Agent.run()  (emits events)       ── loop: think → tools → observe → repeat
   │  tools (read/write/edit/grep/bash/…)       (ai_services/minicode/)
   ▼  HTTP (VMServiceClient)
vm_service · /vms/{id}/…  (FastAPI)          ── per-VM SSH pool + dedicated terminal lane
   │  SSH / SFTP
   ▼
VM Debian  ── /app (user's workspace)
```


## 2. Message flow (end-to-end)

1. The browser opens `wss://…/ws/ai/<container_pk>/`. `AIConsumer.connect()`
   (`ai_services/ai_consumers.py`) validates the user, the **daily quota**
   (`ResourceQuota.ai_uses_left_today()`), container ownership, resolves the
   **active conversation** (pointer in the DB) and replays its history.
2. The user sends `{"text": "..."}`. The consumer checks the quota and calls
   **`run_pipeline(...)`** (`ai_services/minicode/frontends/pipeline.py`).
3. `run_pipeline` runs **everything blocking on a thread** (`asyncio.to_thread`):
   it builds minicode's `Config` (credentials from the `Config` table,
   `workdir=/app`, the `container`), creates the `LLM` and runs `Agent.run()`.
4. `Agent.run()` is a **generator**: it `yield`s events
   (`AssistantTextDelta`, `ToolCallStarted`, `ToolResult`, `Usage`, …). The bridge
   marshals each event onto the event loop and fires the consumer's async
   callbacks, which forward them to the browser as WS messages. This does **not**
   block the Channels loop.
5. Each agent tool calls **vm_service** via `VMServiceClient`, which runs the
   operation inside the VM over SSH.
6. When the turn ends, the consumer records `AIUsageLog` (tokens), persists the
   conversation (a file in the VM) and returns the remaining quota.


## 3. The `minicode` engine (`ai_services/minicode/`)

Agentic core ported from opencode, **decoupled from the interface via events**.
The loop is driven by minicode, not by the OpenAI SDK: each model call is **one
step**; "keep going until done" is handled by the `Agent`.

| File | What it does |
|---|---|
| `agent.py` | The loop (`Agent.run`): assemble context → one LLM step → run tools → feed results back → repeat, until the model replies without requesting tools. `yield`s events; supports subagents (`task`). Caps at `max_steps` (default 50). |
| `llm.py` | Bridge to an OpenAI-style endpoint, streaming. `stream()` `yield`s the text and accumulates tool-calls; returns `{content, tool_calls, usage}`. |
| `session.py` | History in OpenAI format (`role`/`content`/`tool_calls`/`tool`). `sanitize()` repairs broken histories (an `assistant` with `tool_calls` missing its `tool`) that would otherwise make the API reject everything. |
| `events.py` | Event dataclasses (the core's only output channel). `depth`: 0 = main, >0 = subagent. |
| `context.py` | `build_system()`: system prompt + `<env>` block (describes the Debian VM / `/app`). Does **not** read the server's filesystem. |
| `prompts.py` | System prompts (Pequenin + `explore`/`general` subagents + step-limit notice). Documents the environment and `config.json`. |
| `config.py` | `Config` dataclass: credentials/model, `workdir=/app`, `container`, `foreground_timeout`. |
| `frontends/pipeline.py` | Adapter to Django Channels: `run_pipeline()` + `agent` (its `.model`). Sync↔async bridge (worker thread + `run_coroutine_threadsafe`). |
| `tools/` | The model's "hands" (see §4). |

**Subagents**: the `task` tool spawns a child `Agent` (`explore` = read-only, or
`general`) with its own loop and a restricted tool set; it forwards their events
with higher `depth` and returns their final report.


## 4. Tools (`ai_services/minicode/tools/`)

They operate on the **VM** via `VMServiceClient` (not on the server's
filesystem). Relative paths resolve against `/app` (POSIX).

| Tool | Action | VM backend |
|---|---|---|
| `read` | Read a file (numbered, paginated) | `read-file` |
| `write` | Create/overwrite a file | `upload-files` |
| `edit` | Targeted replacement (cascade exact → flexible → block-anchor, whitespace-tolerant) | `read-file` + `upload-files` |
| `glob` | Find files by pattern | `list-dirs` (depth) + fnmatch |
| `grep` | Search content (text/regex) | `search` (grep on the VM) |
| `bash` | Shell command. **Foreground** (~25 s) or **`background=true`** (survives the turn) | `execute-sh` / `start-process` |
| `process` | Status/log or stop of a background job | `process-status` / `stop-process` |
| `todowrite` | Agent's task list (planning) | — (in session) |
| `task` | Delegate to a subagent (`explore`/`general`) | — (subagent) |
| `skill` | Load a reusable skill (`SKILL.md`) on demand — progressive disclosure (see §5.5) | `read-file` + `list-dirs` |
| `search_on_internet` / `read_from_internet` | Web search (DDGS) and URL fetch (requests+bs4) | — (runs on the server) |
| `<server>_<tool>` (dynamic) | Remote **MCP** tools, added per turn when `/app/.pequenin/mcp.json` declares servers (see §5.6) | HTTP/JSON-RPC from the server |
| `<name>` (dynamic) | **Custom tools** from `/app/.pequenin/tools/<name>/` — named, schema'd commands run in the VM (see §5.7) | `execute-sh` (args as JSON on stdin) |

Sets per agent type (`tools/__init__.py`): `build` (main) = all;
`general` = no `task`/`todowrite`; `explore` = read-only + internet (no `skill`).
MCP and custom tools (if any) are added to `build`/`general` only (see §5.6–§5.7).

The VM bridge (client, path resolution, auditing) lives in `tools/vm.py`.


## 5. `config.json`, run and preview

`/app/config.json` is the project descriptor the IDE reads. Implemented schema
(both optional):

```json
{ "run": "<shell command>", "port": <int> }
```

- **`run`** — the IDE's **Run** button saves the files and **pastes the command
  into the interactive terminal** (it does not launch it detached). That's why it
  must be **non-blocking** (`… &`, `setsid -f`, `nohup … &`, `docker compose up -d`);
  otherwise it freezes the terminal.
- **`port`** — the mini-browser previews by running **inside the VM**
  `curl http://localhost:<port>/<path>` and proxying the HTML/CSS/JS (rewriting
  absolute URLs) — see `web_service/vm_manager/proxy_browser_utils.py`. The
  service must listen on that port (bind `0.0.0.0`) and respond quickly.
- A fresh workspace is seeded with `readme.txt` + `config.json` (the `default`
  template); a workspace **reset** deletes everything in `/app` **except those two**.

The agent is instructed (in `prompts.py`) to keep `config.json` correct and to
bring up/verify services with `bash(background=true)` + `process`.


## 5.5 Project instructions (`AGENTS.md`), Skills and `/init`

Ported from opencode, adapted to the VM: everything lives **inside the user's VM**,
persists with the workspace, and is wiped on a workspace reset (like any file under
`/app`). All four new prompt strings live together in `prompts.py`.

- **`AGENTS.md` — project rules.** Each turn the pipeline reads `/app/AGENTS.md`
  (or `/app/CLAUDE.md` as an **alias** — first match wins) from the VM and appends it
  to the system prompt under an `Instructions from: <path>` header: the project's
  custom instructions (build/test commands, architecture, conventions, gotchas).
  Loaded **once per turn** in the worker thread (`project.py`); `build_system` only
  concatenates the result, so the per-step loop stays I/O-free.
- **Skills — reusable instructions, loaded on demand.** A skill is a directory
  `/app/.pequenin/skills/<name>/SKILL.md` with YAML frontmatter (`name` +
  `description` required) and a markdown body (may bundle `scripts/`, `reference/`,
  …). **Progressive disclosure**: the system prompt lists only each skill's
  name/description/location (an `<available_skills>` block); the model loads ONE
  skill's full body when a task matches, via the `skill` tool. Discovery + load live
  in `skills.py`; invalid frontmatter (or a `name` that doesn't equal its folder)
  skips that skill without breaking the turn. Offered to `build` and `general` (not
  `explore`).
  - **Built-in skills** ship with the server under `minicode/builtin_skills/<name>/SKILL.md`
    (read once from the server FS — curated product content, never the user's VM):
    they are ALWAYS available, project-agnostic, and instruction-only (no VM-side
    bundled files). A project skill with the same `name` **overrides** a built-in.
    Today there are three: `authoring-skills` (how the agent writes a skill),
    `authoring-tools` (how it writes a custom tool — see §5.7), and `authoring-mcp`
    (how it configures an MCP server — see §5.6).
  - **The agent can author skills.** The system prompt tells it the convention and
    `bash`/`write` can create `/app/.pequenin/skills/<name>/SKILL.md`; the new skill
    is discovered on the **next** turn. The `authoring-skills` built-in carries the
    full rules.
- **`/init` — generate `AGENTS.md`.** Sending `/init` in the chat runs a normal AI
  turn (consumes quota) whose instruction is the canned `prompts.INIT_PROMPT`: the
  agent scans high-value sources (README, `config.json`, manifests, build/test/lint
  config, CI) and writes — or improves in place — `/app/AGENTS.md`.

> Not implemented (deliberately): user-configurable **agents** (opencode's
> `mode`/`permission`/`model` definitions). Pequeroku's subagents stay hardcoded
> (`explore`/`general`); only `AGENTS.md` + skills were ported.


## 5.6 MCP servers (remote, optional)

Pequenin can use external tools via **MCP (Model Context Protocol)** — `mcp.py`. The
scope is deliberately narrow because opencode's MCP model assumes a single-user CLI on
the user's own machine, while our agent runs on a **shared, multi-tenant server, per
turn, with no persistent session process**:

- **Remote HTTP servers only** (Streamable HTTP / JSON-RPC). No local/stdio (spawning
  user processes on the shared host is unsafe; doing it in the VM would need a new
  vm_service stdio bridge). **Header / API-key auth only** — no OAuth.
- Declared **per-VM** in `/app/.pequenin/mcp.json` (persists with the workspace, wiped
  on reset). Uses the de-facto-standard `mcpServers` key (same as Claude Code / Cursor /
  `.mcp.json`); the legacy `mcp` key is also accepted. `type` defaults to remote,
  `enabled` to true, `headers` carries API-key auth:

  ```json
  { "mcpServers": { "context7": { "url": "https://mcp.context7.com/mcp" } } }
  ```

- Loaded **once per turn** in the pipeline worker thread (`discover_mcp_tools`):
  connect → `initialize` → `tools/list`; each tool is wrapped as a normal minicode
  `Tool` named `<server>_<tool>` and appended to the `build`/`general` toolset for that
  turn. Native tools win on a name collision; total MCP tools are capped at 60
  (context-budget guard).
- **Egress guard (SSRF):** requests leave the shared server, so user URLs pointing at
  private/loopback/link-local hosts are blocked unless `PEQUENIN_MCP_ALLOW_PRIVATE` is
  set. (Hostnames are not DNS-resolved here — a known limit.)
- Everything is **sync** (`requests`), matching the worker-thread model — no async
  bridge, no new dependency. Best-effort: a bad/slow server is skipped and never breaks
  the turn (but each declared server adds one connect + `tools/list` round-trip/turn).


## 5.7 Custom tools (per-VM)

Beyond MCP, the user — or the agent itself — can define **custom tools** in
`custom_tools.py`: named, schema'd commands the agent calls like any built-in. This is
the *safe* extensibility tier — the command runs **inside the user's VM** (the same
sandbox `bash` uses), so it grants no capability `bash` didn't already have (no
shared-host RCE, no SSRF).

- A tool is a directory `/app/.pequenin/tools/<name>/` with a `tool.json` manifest:

  ```json
  { "name": "run-linter",
    "description": "Run ruff on a path. Use before committing Python.",
    "parameters": {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]},
    "command": "python3 run.py" }
  ```

  `name` must equal the folder; `parameters` is the JSON Schema the model sees;
  `command` runs with the tool's own folder as the working directory.
- **Args contract:** the validated arguments are delivered to the command as a JSON
  object on **stdin** (base64 on the wire → no shell-quoting/injection); whatever the
  command writes to stdout/stderr is the tool result.
- Discovered **once per turn** (`discover_custom_tools`, mirrors skills/MCP) and added
  to the `build`/`general` toolset. A native tool wins a name collision (and MCP wins
  over a custom tool); an invalid manifest (bad JSON, `name` != folder, missing
  `description`/`command`) is skipped.
- **Foreground, ~25s** (via `execute-sh`, like foreground `bash`); for long work the
  command should background it itself. The built-in `authoring-tools` skill carries the
  full guide, and the agent is told in its prompt that it can create them.


## 6. Conversations and memory

Supports **multiple conversations** per container, switchable. The single source
of logic is `ai_services/conversations.py` (shared by the consumer and the REST
endpoint).

| Data | Where it lives | Survives a VM reset/rebuild? |
|---|---|---|
| **Content** of each conversation: `/app/.pequenin/ai_memory_<id>.json` (`{"messages":[…]}`) | **VM** | ❌ (by design) |
| **Pointer** to the active conversation: `AIMemory.current_conversation` per `(user, container)` | **DB** | ✅ |

On connect, the consumer reads the pointer (DB), loads that conversation (VM)
and replays its history. `/clear` clears the active conversation.

> Note: the content is VM-only on purpose (no DB backup). The pointer is durable
> in the DB so reconnecting doesn't depend on the VM.


## 7. WebSocket protocol (`/ws/ai/<container_pk>/`)

### Client → server
| Message | Effect |
|---|---|
| `{"text": "..."}` | Chat message in the active conversation (consumes quota) |
| `"/clear"` (as `text`) | Clears the active conversation |
| `"/init"` (as `text`) | Generates/improves `/app/AGENTS.md` (a normal AI turn; consumes quota) |
| `{"action":"list_conversations"}` | Returns `conversations` |
| `{"action":"new_conversation"}` | Creates the next id and switches to it |
| `{"action":"switch_conversation","id":N}` | Loads N and replays its history |
| `{"action":"delete_conversation","id":N}` | Deletes N (if it was active, falls back to another) |

### Server → client
| Event | Fields | For |
|---|---|---|
| `start_text` / `text` / `finish_text` | `content` | Streaming assistant response |
| `connected` | `ai_uses_left_today` | Remaining quota |
| `conversations` | `conversations[]`, `current` | List + active conversation |
| `clear` | — | View reset (on switch/clear) |
| `memory_data` | `memory[]`, `conversation` | Full persisted history |
| `tool_call` | `name`, `args`, `command`, `depth` | The invoked tool + its arguments |
| `tool_result` | `name`, `output` (≤4000 chars), `depth` | What the tool returned |
| `todos` | `todos[]`, `depth` | The agent's task list |
| `subagent_started` / `subagent_finished` | `agent_type`, `prompt`, `depth` | Subagent activity |
| `info` / `error` | `message`, `depth` | Loop notices |
| `usage` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `depth` | Tokens per step |

> The structured events (`tool_call`, `tool_result`, `todos`, `usage`, …) are
> always emitted; the front end may ignore them until it implements them.


## 8. REST endpoints (DRF, `ContainersViewSet`)

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/containers/{id}/conversations/` | `{"conversations":[…],"current":N}` |
| `GET` | `/api/containers/{id}/conversations/{n}/` | `{"conversation_id":n,"messages":[…]}` |
| `DELETE` | `/api/containers/{id}/conversations/{n}/` | `{"conversations":[…],"current":N}` |

Auth + ownership via the usual `ContainersViewSet`.


## 9. VM access layer (vm_service) — coexistence

vm_service serves, on **a single event loop**, both the interactive terminal and
the agent/editor operations. So they coexist without blocking each other:

- **SSH handlers off the loop**: the data endpoints are `def` (Starlette runs
  them in its threadpool) → the loop stays free for the terminal.
- **Per-VM SSH connection pool** (`implementations/ssh_pool.py`): each file/exec
  operation borrows a connection with its **own SFTP** (no races), bounded per VM
  (doesn't exhaust `MaxSessions`).
- **Dedicated terminal lane**: the interactive shell opens **its own** connection
  (`generate_console`), isolated from the agent's churn.
- **Channel cleanup** (`exec_and_close`): each `exec_command` closes its channel →
  no leaked sessions (avoids `ChannelException: Connect failed`).

Long commands (`pip install`, `pytest`, servers) go through `start-process`
(detached with `setsid`, surviving the request) and are queried with
`process-status`.


## 9.5 Platform API + the PequeRoku MCP server (NOT the agent)

PequeRoku exposes its substrate as a public API (`platform_api`, `/api/v1`) and
ships its **own** MCP server (`source/mcp_service/`). Don't confuse the two
MCP-shaped things in this codebase:

| | Who is the agent | Direction |
|---|---|---|
| **§5.6 MCP servers (remote)** | Pequenin | Pequenin is the **client**: it *consumes* external MCP servers as extra tools. |
| **The PequeRoku MCP server** | the external client (Claude Code, Desktop, …) | PequeRoku is the **server**: it *exposes* platform tools; the caller is the brain. |

**Hard boundary — the MCP server never touches the agent.** `mcp_service` and
`platform_api` import **zero** of `ai_services`: no Pequenin, no prompts, no
agent sessions, no chat tools. They are a thin facade over `/api/v1` (containers,
exec, files, ports, one-shot runs). The MCP client already *is* the agent;
PequeRoku provides the hands, not the brain. If you're working on Pequenin, keep
it that way — do not wire `ai_services` into the public API or the MCP server.

Conversely, Pequenin and the public API are **siblings over one substrate**: both
reach VMs through `vm_service` (the agent via `VMServiceClient`; the API via the
shared `vm_manager/orchestration.py` helpers that `ContainersViewSet` and
`platform_api` both call). The agent is, in effect, just another client of the
same machine layer.

- Auth: API keys (`platform_api.APIKey`, scopes `read`<`exec`<`admin`), separate
  from the IDE session. Self-serve from the dashboard's **API & MCP** page
  (`/dashboard/keys`, session-authed `/api/account/api-keys/`); CLI
  `manage.py create_api_key`.
- One-shot ephemeral runs (`POST /api/v1/runs`, sync + async) create + run +
  destroy a VM; `Container.expires_at` + the `reap_expired` reaper guarantee no
  orphans. The run's VM inherits the same network isolation as every other VM.
- Surface, decisions and phases: `docs/platform-api-and-mcp.md` and
  `docs/platform-api-implementation-plan.md`. SDK: `sdk/` (repo root).


## 10. Configuration and quotas

- **LLM credentials**: the `Config` table (`internal_config`) with
  `openai_api_key`, `openai_api_url`, `openai_model`. The pipeline reads them per
  request (the ai_service stays stateless).
- **Quota**: `ResourceQuota.ai_uses_left_today()` limits uses/day; each turn
  records `AIUsageLog` (model + tokens).
- **Model**: `agent.model` is read from `Config` (default `gpt-4o`).


## 11. File map (the essentials)

```
web_service/
  ai_services/
    ai_consumers.py            # AIConsumer (WebSocket): auth, quota, conversations, streaming
    conversations.py           # conversation storage (VM) + pointer (DB)
    minicode/
      agent.py  llm.py  session.py  events.py  context.py  prompts.py  config.py
      project.py               # loads /app/AGENTS.md (or CLAUDE.md alias) per turn
      skills.py                # discover/index/load skills (built-in + /app/.pequenin/skills)
      builtin_skills/          # server-shipped skills, always available (authoring-skills, authoring-tools, authoring-mcp)
      mcp.py                   # remote MCP servers (/app/.pequenin/mcp.json) → per-turn tools
      custom_tools.py          # user-defined tools (/app/.pequenin/tools/) run in the VM → per-turn tools
      frontends/pipeline.py    # run_pipeline + agent (Django/Channels bridge)
      tools/                   # read/write/edit/glob/grep/shell/process/internet/task/todo/skill/vm
  vm_manager/
    views.py                   # ContainersViewSet (incl. conversation endpoints + curl/preview)
    vm_client.py               # VMServiceClient (HTTP to vm_service)
    proxy_browser_utils.py     # preview proxy (curl inside the VM + URL rewriting)
  internal_config/models.py    # Config, AIMemory (pointer), AIUsageLog
  pequeroku/routing.py         # WS route /ws/ai/<pk>/
  front-react/src/components/ide/AiAssistantPanel.tsx   # the IDE chat

vm_service/
  routes/vms.py                # REST endpoints (files/exec/search/process/listening-ports/tty)
  implementations/
    ssh_pool.py                # per-VM SSH connection pool (agent/editor lane)
    ssh_cache.py               # dedicated terminal connection + exec_and_close
    bridge.py                  # TTYBridge (interactive terminal)
    process.py                 # start/status/stop of background processes
    read_from_vm.py  send_file.py
```


## 12. Constraints and gotchas

- **Foreground bash ≈ 25 s** (SSH/HTTP round-trip limit). For anything longer,
  `background=true` + `process`.
- **Conversation content is VM-only**: a VM reset/rebuild wipes it (the DB pointer
  survives, the content does not).
- **`run` must be non-blocking** or it freezes the IDE terminal.
- **The preview** needs the service listening on `config.json.port` and responding
  quickly (the internal `curl` has a short timeout).
- **`max_steps=50`** per turn (loop cap) — a single message may trigger up to 50
  LLM calls; adjustable in `minicode/config.py`.
- **`AGENTS.md` and skills are VM files**: `/app/AGENTS.md` and
  `/app/.pequenin/skills/` persist with the workspace but are wiped on a workspace
  reset (regenerate `AGENTS.md` with `/init`). Loading them adds one `read-file` plus
  one `list-dirs` per turn (best-effort; a VM hiccup degrades to "no project context"
  without failing the turn).
- **MCP is remote-only + best-effort**: only HTTP servers in `/app/.pequenin/mcp.json`
  (header auth; no stdio, no OAuth). Each declared server adds a connect + `tools/list`
  round-trip per turn, user URLs to private hosts are blocked (SSRF guard), and big
  servers are capped at 60 tools to protect the context window.
- **Custom tools run in the VM, foreground ~25s**: `/app/.pequenin/tools/<name>/tool.json`
  commands get their args as JSON on stdin and run via `execute-sh` (same ~25s cap as
  foreground `bash`); they carry the agent's VM privileges — no new risk vs `bash`.


## 13. Roadmap (direction, not implemented)

- Extract the AI into its own microservice (`ai_service`) with a **queue** (Redis
  Streams) to orchestrate runs + **pub/sub** (channel layer) to stream back to the
  browser. Per-VM/user concurrency caps.
- **gRPC** as the internal RPC layer between web↔vm_service (typed contract, native
  streaming for tty/logs/search). Orthogonal to the coexistence fix (already in the
  pool).
- **MCP parity** (beyond the remote-only v1, §5.6): local/stdio servers (needs a
  vm_service stdio bridge or in-VM execution), OAuth for remote servers, connection
  reuse across turns, and per-server enable/disable UI in the IDE.
