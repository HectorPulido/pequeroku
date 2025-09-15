import asyncio
import threading
import time
from typing import Optional

from fastapi import WebSocket
import paramiko

from qemu_manager.models import VMRecord
from .ssh_cache import cache_ssh_and_sftp


def generate_console(container: VMRecord):
    val = cache_ssh_and_sftp(container)
    cli = val["cli"]

    chan = cli.invoke_shell(width=120, height=32)
    chan.settimeout(0.0)

    return cli, chan


class TTYBridge:
    def __init__(self, ws: WebSocket, vm: VMRecord) -> None:
        self.ws = ws
        self.vm = vm
        self.cli: Optional[paramiko.SSHClient] = None
        self.chan: Optional[paramiko.Channel] = None
        self._alive = False

    def start(self) -> None:
        def _run():
            try:
                cli, chan = generate_console(self.vm)
                self.cli = cli
                self.chan = chan
                self._alive = True

                while self._alive and not chan.closed:
                    try:
                        data = chan.recv(4096)
                        if not data:
                            break
                        asyncio.run(self.ws.send_text(data.decode(errors="ignore")))
                    except Exception:
                        time.sleep(0.02)
                self._alive = False
            finally:
                try:
                    if self.chan and not self.chan.closed:
                        self.chan.close()
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    async def send(self, text: str) -> None:
        if not self.chan or self.chan.closed:
            return

        if text.strip() == "ctrlc":
            self.chan.send(b"\x03")
            return

        if text.strip() == "ctrld":
            self.chan.send(b"\x04")
            return

        self.chan.send(text)

    def close(self) -> None:
        self._alive = False
