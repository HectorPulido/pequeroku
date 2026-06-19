"""Binary-safe HTTP proxy into a VM app, over an SSH ``direct-tcpip`` channel.

This replaces the old ``curl``-per-request hack: it forwards a real HTTP request
to ``127.0.0.1:{port}`` *inside* the guest (the channel's destination is resolved
by the guest sshd, so loopback-only dev servers are reachable) and returns the
raw response bytes + status + headers. No base64→PNG guessing, no shell, no
charset loss — the bytes are passed through verbatim.

We send the raw request over the channel and read the whole response into memory
before parsing it (with ``http.client`` over a buffer). Letting ``http.client``
read directly off a paramiko ``Channel`` (``conn.sock = chan``) is flaky — it
trips ``IncompleteRead`` because the channel's EOF/flow-control races the body
reads — so we drain to EOF first and parse from bytes.
"""

from __future__ import annotations

import base64
import http.client
import io
import socket
from dataclasses import dataclass, field
from typing import Iterator

from models import VMRecord, VMProxyRequest, VMProxyResponse
from .preview_pool import borrow_preview

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1). We also drop Host,
# Accept-Encoding and Content-Length here and set our own below.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "accept-encoding",
        "content-length",
    }
)

_RECV_CHUNK = 65536


def build_forward_headers(headers: dict[str, str], target_port: int) -> dict[str, str]:
    """Strip hop-by-hop headers and pin Host / identity encoding / close."""
    fwd = {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}
    fwd["Host"] = f"127.0.0.1:{target_port}"
    # Force identity so the relay receives plain bytes (HTML can be rewritten,
    # binaries pass through untouched) instead of gzip we'd have to inflate.
    fwd["Accept-Encoding"] = "identity"
    # One channel per request; let the app close after the response so the read
    # loop reliably reaches EOF.
    fwd["Connection"] = "close"
    return fwd


def _encode_request(
    method: str, path: str, headers: dict[str, str], body: bytes
) -> bytes:
    lines = [f"{method} {path} HTTP/1.1"]
    lines.extend(f"{k}: {v}" for k, v in headers.items())
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    return head + body


def _recv_all(chan) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            data = chan.recv(_RECV_CHUNK)
        except socket.timeout:
            break  # app held the connection open; stop with what we have
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


class _BufferSocket:
    """A socket-like wrapper so http.client can parse an in-memory response."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self._data)


def proxy_request(vm: VMRecord, req: VMProxyRequest) -> VMProxyResponse:
    """Forward one HTTP request into the VM app and return the raw response."""
    fwd_headers = build_forward_headers(req.headers, req.target_port)
    body = base64.b64decode(req.body_b64) if req.body_b64 else b""
    if body:
        fwd_headers["Content-Length"] = str(len(body))
    method = req.method.upper()

    with borrow_preview(vm) as cli:
        transport = cli.get_transport()
        if transport is None:
            return VMProxyResponse(ok=False, status=502, reason="No SSH transport")

        try:
            chan = transport.open_channel(
                "direct-tcpip",
                ("127.0.0.1", req.target_port),  # app inside the guest
                ("127.0.0.1", 0),
            )
        except Exception as e:
            # No listener on that port inside the VM (app not started yet).
            return VMProxyResponse(
                ok=False,
                status=502,
                reason=f"Cannot reach app on port {req.target_port}: {e}",
            )

        chan.settimeout(req.timeout)
        try:
            chan.sendall(_encode_request(method, req.path or "/", fwd_headers, body))
            raw = _recv_all(chan)
        except Exception as e:
            return VMProxyResponse(ok=False, status=502, reason=f"Proxy error: {e}")
        finally:
            try:
                chan.close()
            except Exception:
                pass

    if not raw:
        return VMProxyResponse(ok=False, status=502, reason="Empty response from app")

    try:
        resp = http.client.HTTPResponse(_BufferSocket(raw), method=method)
        resp.begin()
        body_bytes = resp.read()
        out_headers = list(resp.getheaders())
        status = resp.status
        reason = resp.reason or ""
    except Exception as e:
        return VMProxyResponse(
            ok=False, status=502, reason=f"Response parse error: {e}"
        )

    return VMProxyResponse(
        ok=True,
        status=status,
        reason=reason,
        headers=out_headers,
        body_b64=base64.b64encode(body_bytes).decode("ascii"),
    )


# --------------------------------------------------------------------------- #
# Streaming proxy (SSE / long-lived responses, e.g. AI chatbots, Gradio queue)
#
# The buffered ``proxy_request`` reads the whole response before returning, which
# kills Server-Sent Events: the browser would see nothing until the stream closes
# (or the timeout fires). Here we parse ONLY the response head, then hand back a
# generator that yields the decoded body as it arrives off the SSH channel. The
# channel + borrowed SSH connection stay open for the life of the generator and
# are released in its ``finally`` (covers normal end, errors, and client
# disconnect when the consumer calls ``.close()``).
# --------------------------------------------------------------------------- #

_MAX_HEAD_BYTES = 65536  # refuse absurd header blocks (malformed/hostile upstream)
_STREAM_IDLE_TIMEOUT = 300.0  # end the stream after this much silence from the app

# Re-derived by us, so never relay the upstream's framing/encoding headers.
_DROP_STREAM_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "content-length",
        "content-encoding",  # upstream was forced to identity
    }
)


@dataclass
class StreamResult:
    """Head of a streamed upstream response plus a body generator.

    ``body`` yields decoded body bytes (de-chunked / length-bounded / to-EOF) and
    owns teardown of the SSH channel + connection in its ``finally``.
    """

    ok: bool
    status: int = 502
    reason: str = ""
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: Iterator[bytes] | None = None


def _read_head(chan, timeout: float) -> tuple[bytes, bytes]:
    """Read off the channel until end-of-headers; return ``(head, leftover_body)``."""
    chan.settimeout(timeout)
    buf = b""
    while b"\r\n\r\n" not in buf:
        try:
            data = chan.recv(_RECV_CHUNK)
        except socket.timeout:
            break
        if not data:
            break
        buf += data
        if len(buf) > _MAX_HEAD_BYTES:
            break
    head, sep, rest = buf.partition(b"\r\n\r\n")
    if not sep:
        return b"", b""
    return head, rest


def _parse_head(head: bytes, method: str) -> tuple[int, str, list[tuple[str, str]]]:
    """Parse a raw HTTP response head into ``(status, reason, headers)``."""
    resp = http.client.HTTPResponse(_BufferSocket(head + b"\r\n\r\n"), method=method)
    resp.begin()
    return resp.status, (resp.reason or ""), list(resp.getheaders())


def _framing(headers: list[tuple[str, str]]) -> tuple[str, int]:
    """Decide how the body is framed: chunked, fixed length, or read-to-close."""
    transfer_encoding = ""
    content_length: int | None = None
    for key, value in headers:
        lkey = key.lower()
        if lkey == "transfer-encoding":
            transfer_encoding = value.lower()
        elif lkey == "content-length":
            try:
                content_length = int(value)
            except ValueError:
                content_length = None
    if "chunked" in transfer_encoding:
        return "chunked", 0
    if content_length is not None:
        return "length", content_length
    return "eof", 0


def _raw_source(chan, rest: bytes, idle: float) -> Iterator[bytes]:
    """Yield body bytes: the leftover from head parsing, then channel reads to EOF."""
    if rest:
        yield rest
    chan.settimeout(idle)
    while True:
        try:
            data = chan.recv(_RECV_CHUNK)
        except socket.timeout:
            return  # app went silent past the idle window; treat as end-of-stream
        except Exception:
            return
        if not data:
            return
        yield data


def _limit(src: Iterator[bytes], n: int) -> Iterator[bytes]:
    """Yield at most ``n`` bytes from ``src`` (Content-Length framing)."""
    sent = 0
    for data in src:
        if sent + len(data) >= n:
            yield data[: n - sent]
            return
        sent += len(data)
        yield data


def _dechunk(src: Iterator[bytes]) -> Iterator[bytes]:
    """Incrementally decode HTTP chunked transfer-encoding from a byte stream.

    uvicorn (Gradio, FastAPI chatbots) streams SSE as ``Transfer-Encoding:
    chunked``, so we must de-frame to recover the raw event bytes and emit them as
    each chunk completes — otherwise nothing reaches the browser incrementally.
    """
    buf = b""
    it = iter(src)

    def fill() -> bool:
        nonlocal buf
        chunk = next(it, b"")
        if not chunk:
            return False
        buf += chunk
        return True

    while True:
        while b"\r\n" not in buf:
            if not fill():
                return  # truncated size line
        line, _, buf = buf.partition(b"\r\n")
        size_token = line.split(b";", 1)[0].strip()  # drop chunk extensions
        try:
            size = int(size_token, 16)
        except ValueError:
            return  # malformed framing; stop cleanly
        if size == 0:
            return  # final chunk (trailers ignored)
        while len(buf) < size + 2:  # chunk data + trailing CRLF
            if not fill():
                if buf:
                    yield buf
                return
        yield buf[:size]
        buf = buf[size + 2 :]


def proxy_request_stream(vm: VMRecord, req: VMProxyRequest) -> StreamResult:
    """Like ``proxy_request`` but stream the body instead of buffering it."""
    fwd_headers = build_forward_headers(req.headers, req.target_port)
    body = base64.b64decode(req.body_b64) if req.body_b64 else b""
    if body:
        fwd_headers["Content-Length"] = str(len(body))
    method = req.method.upper()

    cm = borrow_preview(vm)
    cli = cm.__enter__()
    chan = None

    def _cleanup() -> None:
        if chan is not None:
            try:
                chan.close()
            except Exception:
                pass
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass

    try:
        transport = cli.get_transport()
        if transport is None:
            _cleanup()
            return StreamResult(ok=False, status=502, reason="No SSH transport")
        try:
            chan = transport.open_channel(
                "direct-tcpip",
                ("127.0.0.1", req.target_port),
                ("127.0.0.1", 0),
            )
        except Exception as e:
            _cleanup()
            return StreamResult(
                ok=False,
                status=502,
                reason=f"Cannot reach app on port {req.target_port}: {e}",
            )
        chan.settimeout(req.timeout)
        chan.sendall(_encode_request(method, req.path or "/", fwd_headers, body))
        head, rest = _read_head(chan, req.timeout)
        if not head:
            _cleanup()
            return StreamResult(ok=False, status=502, reason="Empty response from app")
        status, reason, headers = _parse_head(head, method)
        kind, length = _framing(headers)
        out_headers = [
            (k, v) for k, v in headers if k.lower() not in _DROP_STREAM_HEADERS
        ]
    except Exception as e:
        _cleanup()
        return StreamResult(ok=False, status=502, reason=f"Proxy stream error: {e}")

    def body_gen() -> Iterator[bytes]:
        try:
            src = _raw_source(chan, rest, _STREAM_IDLE_TIMEOUT)
            if kind == "chunked":
                yield from _dechunk(src)
            elif kind == "length":
                yield from _limit(src, length)
            else:
                yield from src
        finally:
            _cleanup()

    return StreamResult(
        ok=True, status=status, reason=reason, headers=out_headers, body=body_gen()
    )
