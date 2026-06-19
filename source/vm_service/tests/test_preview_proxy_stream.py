import pathlib
import sys

_PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent  # vm_service/
sys.path.insert(0, str(_PKG_ROOT))

from implementations.preview_proxy import (  # noqa: E402
    _dechunk,
    _framing,
    _limit,
    _parse_head,
    _read_head,
)


# --- framing detection ------------------------------------------------------- #
def test_framing_chunked():
    assert _framing([("Transfer-Encoding", "chunked")]) == ("chunked", 0)


def test_framing_content_length():
    assert _framing([("Content-Length", "42")]) == ("length", 42)


def test_framing_eof_for_sse():
    assert _framing([("Content-Type", "text/event-stream")]) == ("eof", 0)


# --- chunked transfer-encoding decoder --------------------------------------- #
def test_dechunk_single_buffer():
    raw = [b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"]
    assert b"".join(_dechunk(iter(raw))) == b"Wikipedia"


def test_dechunk_across_recv_boundaries():
    # Two SSE events split awkwardly across recv() reads (size line, data and CRLF
    # all arrive separately) — the decoder must still recover the exact bytes.
    raw = [
        b"9\r\n",
        b"data: a\n\n",  # 9 bytes
        b"\r\n9\r\ndata: b\n\n\r\n",
        b"0\r\n\r\n",
    ]
    assert b"".join(_dechunk(iter(raw))) == b"data: a\n\ndata: b\n\n"


def test_dechunk_ignores_chunk_extensions():
    raw = [b"4;foo=bar\r\nWiki\r\n0\r\n\r\n"]
    assert b"".join(_dechunk(iter(raw))) == b"Wiki"


# --- content-length framing -------------------------------------------------- #
def test_limit_truncates_to_n():
    assert b"".join(_limit(iter([b"abc", b"defg"]), 5)) == b"abcde"


def test_limit_stops_at_exact_length():
    assert b"".join(_limit(iter([b"hello"]), 5)) == b"hello"


# --- response head parsing --------------------------------------------------- #
def test_parse_head_extracts_status_and_headers():
    head = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nX-Foo: bar"
    status, reason, headers = _parse_head(head, "GET")
    assert status == 200
    assert reason == "OK"
    pairs = {k.lower(): v for k, v in headers}
    assert pairs["content-type"] == "text/event-stream"
    assert pairs["x-foo"] == "bar"


class _FakeChan:
    """Minimal paramiko-channel stand-in feeding canned recv() parts."""

    def __init__(self, parts):
        self._parts = list(parts)

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        return self._parts.pop(0) if self._parts else b""


def test_read_head_splits_headers_from_body():
    chan = _FakeChan(
        [b"HTTP/1.1 200 OK\r\nContent-Type: text/event", b"-stream\r\n\r\ndata: x\n\n"]
    )
    head, rest = _read_head(chan, 1.0)
    assert head == b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream"
    assert rest == b"data: x\n\n"


def test_read_head_empty_when_no_header_terminator():
    chan = _FakeChan([b"HTTP/1.1 200 OK\r\n"])  # never reaches the blank line
    head, rest = _read_head(chan, 1.0)
    assert head == b""
    assert rest == b""
