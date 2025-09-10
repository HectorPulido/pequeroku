import asyncio
import threading
import time
from typing import Optional

from fastapi import WebSocket
import paramiko


from qemu_manager.crypto import _load_pkey


def generate_console(key_path, host, port, user):
    k = _load_pkey(key_path)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(
        host,
        port=port,
        username=user,
        pkey=k,
        look_for_keys=False,
        banner_timeout=120,
        auth_timeout=120,
        timeout=30,
    )
    chan = cli.invoke_shell(width=120, height=32)
    chan.settimeout(0.0)

    return cli, chan


class TTYBridge:
    def __init__(
        self, ws: WebSocket, host: str, port: int, user: str, key_path: str
    ) -> None:
        self.ws = ws
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self.cli: Optional[paramiko.SSHClient] = None
        self.chan: Optional[paramiko.Channel] = None
        self._alive = False

    def start(self) -> None:
        def _run():
            try:
                cli, chan = generate_console(
                    self.key_path, self.host, self.port, self.user
                )
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
                try:
                    if self.cli:
                        self.cli.close()
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
