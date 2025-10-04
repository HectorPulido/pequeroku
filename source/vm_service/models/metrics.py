from __future__ import annotations
from pydantic import BaseModel


class MachineMetrics(BaseModel):
    ts: float | int
    cpu_percent: float | int | None
    rss_bytes: int | None
    rss_human: str | None
    rss_mib: float | int | None
    num_threads: int | None
    io: dict[str, object] | None
