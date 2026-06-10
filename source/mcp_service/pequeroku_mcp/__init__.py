"""PequeRoku MCP server: a thin facade over the public /api/v1 surface.

Platform-only by design: it gives an MCP client (Claude Code, Claude Desktop, ...)
hands to create VMs, run code, move files and inspect ports — never the agent
(Pequenin). The client already IS the agent; PequeRoku is the sandbox.
"""

__all__ = ["__version__"]
__version__ = "1.0.0"
