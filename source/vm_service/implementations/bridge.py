import asyncio
import threading
import time

from fastapi import WebSocket
import paramiko

from models import VMRecord
from .ssh_cache import generate_console


class TTYBridge:
    def __init__(self, ws: WebSocket, vm: VMRecord) -> None:
        self.ws: WebSocket = ws
        self.vm: VMRecord = vm
        self.cli: paramiko.SSHClient | None = None
        self.chan: paramiko.Channel | None = None
        self._alive: bool = False

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
