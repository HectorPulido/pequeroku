#!/usr/bin/env bash
set -euo pipefail

[ -f .env ] && . ./.env || echo "No .env file, continuing..."

echo "Starting PequeRoku MCP server (streamable-http) on ${PEQUEROKU_MCP_HOST:-0.0.0.0}:${PEQUEROKU_MCP_PORT:-8002}..."
exec python -m pequeroku_mcp.server
