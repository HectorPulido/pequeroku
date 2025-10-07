import asyncio
import threading
import time
import base64

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
                        asyncio.run(
                            self.ws.send_text(base64.b64encode(data).decode("ascii"))
                        )
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

    async def send(self, data: bytes | str) -> None:
        if not self.chan or self.chan.closed:
            return

        if isinstance(data, (bytes, bytearray)):
            self.chan.send(data)
            return

        s = data.strip()
        if s == "ctrlc":
            self.chan.send(b"\x03")
            return

        if s == "ctrld":
            self.chan.send(b"\x04")
            return

        # Send as-is (no forced newline)
        self.chan.send(data)

    def close(self) -> None:
        self._alive = False
