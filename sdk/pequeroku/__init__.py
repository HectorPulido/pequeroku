"""PequeRoku Python SDK — a thin, hand-polished client over the public /api/v1.

from pequeroku import PequeRoku

pq = PequeRoku(api_key="pk_...", base_url="https://your-host")
print(pq.run("echo hello").stdout)
"""

from .client import PequeRoku, PequeRokuError, RunResult

__all__ = ["PequeRoku", "PequeRokuError", "RunResult"]
__version__ = "1.0.0"
