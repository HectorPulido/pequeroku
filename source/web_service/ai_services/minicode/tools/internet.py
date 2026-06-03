"""Herramientas de internet: búsqueda web y lectura de URLs.

No dependen de la VM (corren en el servidor de Django, dentro del hilo worker).
Portadas del agente viejo de Pequeroku. Las dependencias (ddgs, requests, bs4) se
importan de forma perezosa para no cargarlas si el agente nunca las usa.
"""

from __future__ import annotations

from .base import Tool, ToolContext, truncate

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_PAGE_CHARS = 8000


class WebSearchTool(Tool):
    name = "search_on_internet"
    read_only = True
    description = (
        "Search the public internet (DuckDuckGo). Use good search-fu: returns the top "
        "results with title, url and snippet. Follow up with read_from_internet to "
        "open a specific result."
    )
    parameters = {
        "type": "object",
        "properties": {
            "search_query": {"type": "string", "description": "Query to search for."},
        },
        "required": ["search_query"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        query = str(args.get("search_query", "")).strip()
        if not query:
            return "Error: missing search_query."
        try:
            from ddgs import DDGS

            results = list(DDGS().text(query, max_results=5, timeout=5))
        except Exception as e:
            return f"Search error: {e}"
        if not results:
            return "No results."

        lines: list[str] = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href") or r.get("url", "")
            body = r.get("body", "")
            lines.append(f"- {title}\n  {href}\n  {body}")
        return truncate("\n".join(lines))


class WebReadTool(Tool):
    name = "read_from_internet"
    read_only = True
    description = (
        "Open a URL and return its readable text (scripts/styles stripped). Be careful "
        "with what you open. Content is truncated to a reasonable length."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open."},
        },
        "required": ["url"],
    }

    def execute(self, args: dict, ctx: ToolContext) -> str:
        url = str(args.get("url", "")).strip()
        if not url:
            return "Error: missing url."
        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get(url, headers={"User-Agent": _DEFAULT_UA}, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return f"Error opening {url}: {e}"

        soup = BeautifulSoup(resp.text, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines()]
        cleaned = "\n".join(ln for ln in lines if ln)
        if len(cleaned) > _MAX_PAGE_CHARS:
            cleaned = cleaned[:_MAX_PAGE_CHARS] + "\n\n[content truncated]"
        return cleaned or "(no readable text)"
