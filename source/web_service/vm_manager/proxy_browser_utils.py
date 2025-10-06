import base64
import re
import urllib.parse
from typing import Any, cast

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from vm_manager.models import Container
from vm_manager.vm_client import VMServiceClient


# Helpers
def ensure_trailing_slash(u: str) -> str:
    """
    Ensure relative URLs end with "/".
    Keep query/hash suffix in place by only appending if missing at the end.
    """
    u = u.strip()
    if not u:
        return u
    # Leave external schemes or protocol-relative untouched
    if re.match(
        r"(?:[a-z][a-z0-9+.\-]*:|//|data:|javascript:|mailto:|tel:)", u, flags=re.I
    ):
        return u
    # Leave absolute paths (handled by encode_url) untouched
    if u.startswith("/"):
        return u
    # If it doesn't end with "/", add it (after any ? or # if present)
    if not u.endswith("/"):
        u = u + "/"
    return u


def encode_url(path: str, prefix: str) -> str:
    """
    Encode an absolute path like '/a/b' into '{prefix}{encoded}/', e.g. 'a%2Fb'.
    Mirrors original logic: strips leading '/', URL-encodes the remainder with no "safe" chars,
    and appends a trailing slash.
    """
    original = path
    core = original.strip().lstrip("/")  # "/a/b" -> "a/b"
    encoded = urllib.parse.quote(core, safe="")  # "a%2Fb"
    return prefix + encoded + "/"


def create_fix_srcset(prefix: str):
    def fix_srcset(match: re.Match[Any]) -> str:
        items = []
        for part in match.group(2).split(","):
            tokens = part.strip().split()
            if not tokens:
                continue
            url, rest = tokens[0], " ".join(tokens[1:])
            if url.startswith("/") or url.startswith(" /"):
                url = encode_url(url, prefix)
            else:
                url = ensure_trailing_slash(url)
            items.append(url + ((" " + rest) if rest else ""))
        return match.group(1) + ", ".join(items) + match.group(3)

    return fix_srcset


def rewrite_paths(content: str, prefix: str, content_path: str) -> str:
    """
    Rewrites absolute and relative paths inside HTML/CSS/JS content so that:
      - Absolute paths (starting with "/") are re-encoded and prefixed.
      - Relative paths (in certain HTML attributes and srcset) are ensured to end with "/".
      - For HTML, injects <base href="{prefix}"> as the first element in <head>.
    """
    if not prefix.endswith("/"):
        prefix += "/"

    is_css = ".css" in content_path
    is_js = ".js" in content_path

    if is_css:
        # Absolute URLs inside CSS url(...) – rewrite
        content = re.sub(
            r'(?i)url\((["\']?)(\s*/[^)\'"]+)\1\)',
            lambda m: f"url({m.group(1)}{encode_url(m.group(2), prefix)}{m.group(1)})",
            content,
        )
        # Absolute URLs inside CSS @import – rewrite
        return re.sub(
            r'(?i)@import\s+(["\'])(\s*/[^"\']+)\1',
            lambda m: f"@import {m.group(1)}{encode_url(m.group(2), prefix)}{m.group(1)}",
            content,
        )
        # Keep relative URLs in CSS untouched to avoid breaking image paths

    if is_js:
        # Absolute string literals in JS – rewrite
        return re.sub(
            r'(?i)(["\'])(\s*/[^"\']+)\1',
            lambda m: f"{m.group(1)}{encode_url(m.group(2), prefix)}{m.group(1)}",
            content,
        )

    # Ensure a single <base href="{prefix}"> inside <head> (with no filename)
    content = re.sub(r"(?is)<base[^>]*>", "", content)
    if re.search(r"(?is)<head[^>]*>", content):
        content = re.sub(
            r"(?is)(<head[^>]*>)",
            r'\1<base href="' + re.escape(prefix) + r'">',
            content,
            count=1,
        )
    else:
        content = f'<head><base href="{prefix}"></head>' + content

    # 1) Absolute paths in attributes (href/src/action/poster) – rewrite
    content = re.sub(
        r'(?i)(\s(?:href|src|action|poster)\s*=\s*["\'])(\s*/[^"\']+)',
        lambda m: m.group(1) + encode_url(m.group(2), prefix),
        content,
    )

    # 2) Relative paths in attributes – ensure trailing slash
    content = re.sub(
        r'(?i)(\s(?:href|src|action|poster)\s*=\s*["\'])(?!\s*(?:/|https?:|data:|javascript:|mailto:|tel:|//))([^"\']+)',
        lambda m: m.group(1) + ensure_trailing_slash(m.group(2)),
        content,
    )

    # 3) srcset: absolute entries rewritten, relative entries ensured trailing slash
    f_srcset = create_fix_srcset(prefix)
    return re.sub(r'(?i)(\ssrcset\s*=\s*["\'])([^"\']+)(["\'])', f_srcset, content)


def parse_get(
    port: int,
    path: str | None,
    container: Container,
    base_url: str,
    service: VMServiceClient,
):
    """
    Execute a curl inside the container's VM and proxy back a slightly modified version.
    """
    # Decode the requested path (may be None)
    decoded_path = urllib.parse.unquote(path or "")

    try:
        # Run curl in the target container namespace and capture stdout
        cmd = f"curl http://localhost:{port}/{decoded_path} --output -"
        response = service.execute_sh(str(container.container_id), cmd)
    except Exception as exc:
        return Response(
            f"Something went wrong {exc}", status=status.HTTP_400_BAD_REQUEST
        )

    stdout = cast(str, response.get("stdout", ""))

    if len(stdout) < 5:
        # Minimal content guard (preserve original heuristic)
        return Response(status=status.HTTP_404_NOT_FOUND)

    try:
        # If stdout is base64 -> return as PNG
        image_data = base64.b64decode(stdout)
        return HttpResponse(image_data, content_type="image/png")
    except Exception:
        # Not base64-encoded image; continue to path rewriting
        pass

    rewritten = rewrite_paths(stdout, base_url, decoded_path)

    content_type: str | None = None
    if ".css" in decoded_path:
        content_type = "text/css"
    if ".js" in decoded_path:
        content_type = "application/javascript"

    return HttpResponse(rewritten, content_type=content_type)
