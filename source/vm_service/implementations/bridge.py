import asyncio
import socket
import threading
import collections

from fastapi import WebSocket
import paramiko

from models import VMRecord
from .ssh_cache import generate_console

# How many output frames may be in flight (scheduled on the loop but not yet sent)
# before the reader thread waits for the oldest to drain. Bounds memory while still
# letting reads and sends pipeline instead of round-tripping per frame.
_MAX_INFLIGHT = 32
# Read window. TUIs (opencode, vim, htop) repaint in large bursts; a bigger window
# pulls a redraw in fewer recv() calls.
_RECV_CHUNK = 32768
_MAX_FRAME = 262144


class TTYBridge:
    def __init__(
        self,
        ws: WebSocket,
        vm: VMRecord,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.ws: WebSocket = ws
        self.vm: VMRecord = vm
        self.cli: paramiko.SSHClient | None = None
        self.chan: paramiko.Channel | None = None
        self._alive: bool = False
        # Event loop that owns `ws`; reader thread schedules sends here instead of
        # spinning up a throwaway loop per chunk (asyncio.run was the main bottleneck).
        self.loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()
        # Input that arrives before the upstream shell exists is buffered here and
        # flushed once the channel is ready, so callers never need to guess a delay
        # before sending the first command.
        self._lock = threading.Lock()
        self._pending: list[bytes | str] = []
        self._ready: bool = False

    def start(self) -> None:
        def _run():
            try:
                cli, chan = generate_console(self.vm)
                self.cli = cli
                self.chan = chan
                self._alive = True

                # Flush anything that was sent while the shell was still starting.
                # Done inside the lock so a concurrent send() can't overtake the
                # buffered items and reorder input.
                with self._lock:
                    self._ready = True
                    for payload in self._pending:
                        try:
                            chan.send(payload)
                        except Exception:
                            break
                    self._pending = []

                # Frames scheduled on the loop but not yet flushed. Ordering is
                # preserved because run_coroutine_threadsafe schedules FIFO.
                inflight: "collections.deque[asyncio.Future]" = collections.deque()

                # `chan` has a small read timeout (set in generate_console), so recv()
                # returns the instant data arrives and otherwise wakes every ~0.2s just
                # to re-check `_alive`. No busy-poll, no fixed latency on the echo.
                while self._alive and not chan.closed:
                    try:
                        data = chan.recv(_RECV_CHUNK)
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                    if not data:
                        break

                    # Coalesce whatever is already buffered into a single frame so
                    # large redraws (`clear`, TUIs) ship in one send. recv_ready() is
                    # non-blocking, so this never adds latency for small echoes.
                    try:
                        while chan.recv_ready() and len(data) < _MAX_FRAME:
                            more = chan.recv(_RECV_CHUNK)
                            if not more:
                                break
                            data += more
                    except Exception:
                        pass

                    # Binary frame (no base64): saves 33% size + encode/decode CPU on
                    # the hot output path.
                    fut = asyncio.run_coroutine_threadsafe(
                        self.ws.send_bytes(bytes(data)), self.loop
                    )
                    inflight.append(fut)

                    # Reap finished sends without blocking, so reads and sends pipeline.
                    while inflight and inflight[0].done():
                        inflight.popleft()

                    # Backpressure: if the loop falls behind, wait for the oldest frame.
                    if len(inflight) >= _MAX_INFLIGHT:
                        try:
                            inflight.popleft().result()
                        except Exception:
                            break
                self._alive = False
            finally:
                try:
                    if self.chan and not self.chan.closed:
                        self.chan.close()
                except Exception:
                    pass
                # Close the terminal's dedicated SSH connection so it does not
                # linger after the websocket goes away.
                try:
                    if self.cli is not None:
                        self.cli.close()
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _to_payload(data: bytes | str) -> bytes | str:
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)

        s = data.strip()
        if s == "ctrlc":
            return b"\x03"
        if s == "ctrld":
            return b"\x04"
        # Send as-is (no forced newline)
        return data

    async def send(self, data: bytes | str) -> None:
        payload = self._to_payload(data)

        # If the shell channel is not ready yet, buffer instead of dropping. The lock
        # closes the race against the reader thread flipping `_ready` and draining.
        with self._lock:
            if not self._ready or not self.chan or self.chan.closed:
                self._pending.append(payload)
                return

        self.chan.send(payload)

    def close(self) -> None:
        self._alive = False
