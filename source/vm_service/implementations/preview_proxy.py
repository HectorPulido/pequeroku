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
