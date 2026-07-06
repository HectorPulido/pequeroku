# PequeRoku MCP server

A thin [MCP](https://modelcontextprotocol.io) server that gives any MCP client
(Claude Code, Claude Desktop, opencode, …) **hands** on a PequeRoku sandbox:
create VMs, run code, move files, inspect ports. It is a facade over the public
`/api/v1` surface — no privileged side paths, full dogfooding of the contract.

> Platform-only by design: it never exposes the agent (Pequenin). The MCP client
> already *is* the agent; PequeRoku is the sandbox. The blast radius of anything
> it runs is one isolated VM, not your laptop.

On connect the server hands the client a block of **instructions**
(`prompts.py`): what a PequeRoku VM is (Debian, working dir `/app`), one-shot vs
persistent workflow, how credits/types work, and the preview/ports flow — so the
agent starts with context instead of guessing.

## Tools (10)

| Tool | Does |
|---|---|
| `list_types` | VM flavors your key may use, with specs + credit cost |
| `run_code` | code/files + command → output; creates and destroys a throwaway VM |
| `list_containers` | your persistent containers with status + flavor |
| `get_or_create_container` | return the named container or create it (`name`, `type?`) |
| `container_exec` | run a command in a container; `background=true` → `process_id` |
| `process_status` | status + output of a background process |
| `write_files` | batch-write files to a container |
| `read_path` | file → contents; dir → listing |
| `get_preview` | listening ports + `preview_url`s; with `port`/`path` → fetch the live app response |
| `destroy_container` | destroy a container (requires `confirm=true`) |

**Preview access.** The preview endpoint (`{PEQUEROKU_API_URL}/api/containers/<id>/preview/<port>/<path>`)
authenticates with your platform API key — no login session needed. `get_preview`
uses it for you when you pass a `port`. To reach it directly (or hand a browser a
link), present the key as an `Authorization: Bearer pk_...` header **or** a
`?__pk_token=pk_...` query param. It is owner-only (you only see your own
containers), and a query-param hit sets a short-lived, path-scoped cookie so an
embedded page's assets load too.

## Prompts (3)

Reusable, task-shaped starters the client can offer (its "Prompts" list). Each
expands into a user message that bakes in the right tool workflow; wording lives
in `prompts.py`.

| Prompt | Argument | Does |
|---|---|---|
| `run_in_sandbox` | `task` | run code/a command in a throwaway VM and report the result |
| `deploy_web_app` | `app` | build + serve a web app in a persistent container, with a preview |
| `setup_workspace` | `name` | get/create a named persistent workspace and report its state |

## Run

```bash
cd source/mcp_service
poetry install
PEQUEROKU_API_URL=http://localhost PEQUEROKU_API_KEY=pk_xxx poetry run pequeroku-mcp
```

Transport is **streamable HTTP** on `:8002` (path `/mcp`), proxied by nginx at
`/mcp/`. In `docker-compose` it runs as the `mcp_service` container.

## Connect a client

The API key travels in the client config as an `Authorization` header; it takes
precedence over `PEQUEROKU_API_KEY`. Each key's scopes (`read`/`exec`/`admin`)
are enforced by the API, so you decide how much power each agent gets.

```bash
claude mcp add --transport http pequeroku https://YOUR_HOST/mcp/ \
  --header "Authorization: Bearer pk_xxx"
```

## Config (env)

| Var | Default | Meaning |
|---|---|---|
| `PEQUEROKU_API_URL` | `http://web:8000` | Base URL of web_service (`/api/v1` is appended) |
| `PEQUEROKU_API_KEY` | — | Shared fallback key for single-tenant; per-request Bearer takes precedence |
| `PEQUEROKU_MCP_HOST` / `PEQUEROKU_MCP_PORT` | `0.0.0.0` / `8002` | Bind address |
| `PEQUEROKU_MCP_OUTPUT_LIMIT` | `65536` | Byte cap on tool output |

> **Auth:** in the default (multi-tenant) posture each caller must send
> `Authorization: Bearer pk_...`; nginx rejects credential-less requests to
> `/mcp` with `401` before they reach the server, and with no `PEQUEROKU_API_KEY`
> set the server itself stays unauthorized — closed by default, never an open
> relay. Set `PEQUEROKU_API_KEY` only for single-tenant/private deployments.
