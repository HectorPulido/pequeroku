"""mini-code: a miniature (but powerful) version of opencode's agentic core.

The heart of the system is the *agentic loop* (``agent.Agent.run``): think → call
tools → see results → repeat, until the model responds without requesting more
tools. The rest are supporting pieces: tools (the model's hands), context
assembly, and the bridge to an OpenAI-compatible LLM.
"""

__version__ = "0.1.0"
