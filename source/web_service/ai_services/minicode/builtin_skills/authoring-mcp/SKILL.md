---
name: authoring-mcp
description: Add, connect, enable/disable or configure a remote MCP server for this workspace. Use when the user asks to connect to an MCP server, gives you an MCP URL, or wants to manage MCP tools.
---

# Configuring MCP servers

MCP (Model Context Protocol) servers expose extra tools to you. In this workspace you
connect **remote (HTTP)** MCP servers by writing one config file; their tools then
appear in your toolset, named `<server>_<tool>`.

## Where the config lives

    /app/.pequenin/mcp.json

## Schema

Use the standard `mcpServers` key (the same one Claude Code / Cursor / `.mcp.json`
use). The minimal form is just a name and a `url`:

    {
      "mcpServers": {
        "context7": { "url": "https://mcp.context7.com/mcp" }
      }
    }

Full form with the optional fields:

    {
      "mcpServers": {
        "<server-name>": {
          "url": "https://.../mcp",
          "headers": { "Authorization": "Bearer ..." },
          "enabled": true
        }
      }
    }

- `<server-name>` — your label; it becomes the prefix of every tool from that server
  (`<server-name>_<tool>`). Keep it short and simple.
- `url` — REQUIRED. The server's HTTP endpoint (Streamable HTTP / JSON-RPC).
- `headers` — optional, for API-key / bearer auth. OAuth is NOT supported.
- `enabled` — optional, defaults to `true`; set `false` to keep it but turn it off.
- `timeout` — optional, in milliseconds (default 30000).

(The parser is tolerant of other common shapes: the `mcp` (opencode) and `servers`
(VS Code) keys also work, `type` is optional (`remote`/`http`/`sse`/none all mean
remote), and a server is off if `enabled: false` or `disabled: true`. Only remote HTTP
works — `local`/`stdio` servers are ignored. When in doubt, write the `mcpServers`
form above.)

## How to add a server

1. `read` the existing `/app/.pequenin/mcp.json` first (if it exists) so you MERGE the
   new server in — do not overwrite other servers already configured.
2. `write` the file back with the new server added under the `mcp` object.
3. Tell the user the tools will be available on their **NEXT** message: servers are
   discovered at the start of each turn, so a server added this turn is not usable
   until the next one.

## Rules and limits

- **Remote HTTP only.** A `"type": "local"` / stdio server is ignored.
- **Header / API-key auth only.** No OAuth flow.
- Requests leave a shared server, so a `url` pointing at a **private/loopback** host
  (`localhost`, `127.x`, `10.x`, `192.168.x`, `169.254.x`, ...) is BLOCKED for
  security. Use a public URL.
- A native tool wins a name collision, and the total number of MCP tools is capped at
  60 (to protect the context window).
- To turn a server off without losing its config, set `"enabled": false`.
- Keep the file valid JSON — a malformed `mcp.json` disables ALL MCP for the turn.

## Example

User: "Connect to Context7 at https://mcp.context7.com/mcp"

    {
      "mcpServers": {
        "context7": { "url": "https://mcp.context7.com/mcp" }
      }
    }

Then tell them: "Done — Context7's tools (`context7_*`) will be available on your next
message."
