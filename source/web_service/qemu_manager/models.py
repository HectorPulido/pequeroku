from dataclasses import dataclass
from typing import Optional
import subprocess


@dataclass
class VMProc:
    """
    Lightweight handle to a running (or reattached) QEMU VM.
    Mirrors the original structure to avoid breaking external code.
    """

    workdir: str
    overlay: str
    seed_iso: str
    port_ssh: int
    proc: Optional[subprocess.Popen] = None
    console_log: Optional[str] = None
    pidfile: Optional[str] = None
