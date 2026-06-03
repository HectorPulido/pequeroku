"""Tests for the internet tools (web search / fetch) without real network.

``ddgs`` is injected as a fake module; ``requests.get`` is monkeypatched (bs4 runs
for real over the fake HTML).
"""
from __future__ import annotations

import sys
import types

import requests as requests_mod

from ai_services.minicode.tools.internet import WebSearchTool, WebReadTool


def test_web_search_formats_results(monkeypatch):
    class FakeDDGS:
        def text(self, query, max_results=5, timeout=5):
            return [
                {"title": "T1", "href": "http://a", "body": "b1"},
                {"title": "T2", "url": "http://b", "body": "b2"},
            ]

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))

    out = WebSearchTool().execute({"search_query": "python"}, None)
    assert "T1" in out and "http://a" in out and "b1" in out
    assert "T2" in out and "http://b" in out


def test_web_search_empty_query_is_guarded():
    assert "search_query" in WebSearchTool().execute({"search_query": "  "}, None)


def test_web_search_no_results(monkeypatch):
    class FakeDDGS:
        def text(self, *a, **k):
            return []

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    assert WebSearchTool().execute({"search_query": "x"}, None) == "Sin resultados."


def test_web_search_reports_errors(monkeypatch):
    class FakeDDGS:
        def text(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    out = WebSearchTool().execute({"search_query": "x"}, None)
    assert "Error" in out and "boom" in out


def test_web_read_strips_scripts_and_returns_text(monkeypatch):
    html = (
        "<html><head><script>var x=1</script><style>a{}</style></head>"
        "<body><h1>Hi</h1><p>Body text</p></body></html>"
    )

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        requests_mod, "get", lambda url, headers=None, timeout=None: FakeResp()
    )
    out = WebReadTool().execute({"url": "http://x"}, None)
    assert "Hi" in out and "Body text" in out
    assert "var x=1" not in out  # script content stripped


def test_web_read_reports_errors(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("conn refused")

    monkeypatch.setattr(requests_mod, "get", boom)
    out = WebReadTool().execute({"url": "http://x"}, None)
    assert "Error" in out and "conn refused" in out


def test_web_read_empty_url_is_guarded():
    assert "url" in WebReadTool().execute({"url": ""}, None)
