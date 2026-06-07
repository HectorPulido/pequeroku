"""Interface adapters (frontends) for the mini-code core.

The core (``minicode.agent``) knows about no interface: it ``yield``s events
(``minicode.events``). Each frontend in this package CONSUMES that event stream and
materializes it its own way. The terminal one lives here; a web app (SSE/websocket)
or a JSON API would be sibling modules that reuse the same core without touching it.
"""
