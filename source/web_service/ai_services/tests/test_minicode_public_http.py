import io
import socket

import pytest
import requests
from urllib3 import HTTPResponse

from ai_services.minicode.public_http import public_http_session


def _dns_result(address):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))


def test_public_http_pins_destination_but_keeps_https_origin(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kw: [_dns_result("8.8.8.8")]
    )
    with public_http_session() as session:
        req = requests.Request("GET", "https://public.example/app").prepare()
        pool = session.get_adapter(req.url).get_connection_with_tls_context(req, True)
        assert pool.host == "8.8.8.8"
        assert pool.assert_hostname == "public.example"
        assert pool.conn_kw["server_hostname"] == "public.example"
        assert req.headers["Host"] == "public.example"
        assert session.trust_env is False


def test_public_http_rejects_mixed_dns_before_connecting(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kw: [_dns_result("8.8.8.8"), _dns_result("127.0.0.1")],
    )
    with public_http_session() as session:
        with pytest.raises(requests.exceptions.InvalidURL, match="Non-public"):
            session.get("https://public.example", timeout=1)


def test_public_http_checks_destination_again_on_redirect(monkeypatch):
    def resolve(host, *args, **kw):
        return [_dns_result("8.8.8.8" if host == "public.example" else "10.0.0.1")]

    ports_used = []

    def respond(pool, *args, **kwargs):
        ports_used.append(pool.host)
        return HTTPResponse(
            status=302,
            headers={"Location": "https://restricted.example/"},
            body=io.BytesIO(b""),
            preload_content=False,
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr("urllib3.HTTPSConnectionPool.urlopen", respond)
    with public_http_session() as session:
        with pytest.raises(requests.exceptions.InvalidURL, match="Non-public"):
            session.get("https://public.example", timeout=1)
    assert ports_used == ["8.8.8.8"]
