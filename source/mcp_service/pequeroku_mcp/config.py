"""Runtime config for the MCP server (all via env)."""

from __future__ import annotations

import os

# Base URL of the web_service exposing /api/v1. Internal by default (behind nginx).
API_URL = os.getenv("PEQUEROKU_API_URL", "http://web:8000")

# Fallback API key for single-tenant deployments. Per-request keys from the MCP
# client's Authorization header take precedence (see server._resolve_api_key).
# Unset by default: with no key and no Bearer token the server stays unauthorized
# (401), so it never becomes an open relay just by being deployed.
API_KEY = os.getenv("PEQUEROKU_API_KEY", "")

# Truncate tool outputs to keep the agent's context bounded (same spirit as the
# API's own truncation).
OUTPUT_LIMIT = int(os.getenv("PEQUEROKU_MCP_OUTPUT_LIMIT", str(64 * 1024)))

# HTTP host/port for the streamable-HTTP transport.
HOST = os.getenv("PEQUEROKU_MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("PEQUEROKU_MCP_PORT", "8002"))
