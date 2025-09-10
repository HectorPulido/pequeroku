import subprocess
from typing import Iterable


def _run_checked(cmd: Iterable[str]) -> None:
    """Wrapper over subprocess.run with check=True for brevity."""
    subprocess.run(list(cmd), check=True)
