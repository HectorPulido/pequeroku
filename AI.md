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
| `search_on_internet` / `read_from_internet` | Web search (DDGS) and URL fetch (requests+bs4) | — (runs on the server) |

Sets per agent type (`tools/__init__.py`): `build` (main) = all;
`general` = no `task`/`todowrite`; `explore` = read-only + internet.

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
      frontends/pipeline.py    # run_pipeline + agent (Django/Channels bridge)
      tools/                   # read/write/edit/glob/grep/shell/process/internet/task/todo/vm
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


## 13. Roadmap (direction, not implemented)

- Extract the AI into its own microservice (`ai_service`) with a **queue** (Redis
  Streams) to orchestrate runs + **pub/sub** (channel layer) to stream back to the
  browser. Per-VM/user concurrency caps.
- **gRPC** as the internal RPC layer between web↔vm_service (typed contract, native
  streaming for tty/logs/search). Orthogonal to the coexistence fix (already in the
  pool).
