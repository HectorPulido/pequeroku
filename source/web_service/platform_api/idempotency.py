"""Idempotency-Key support for unsafe, side-effectful POSTs.

A client may send ``Idempotency-Key: <uuid>`` on ``POST /containers`` and
``POST /runs``; a retry with the same key (same key owner) returns the cached
response instead of creating a second resource. Backed by Django's cache (Redis
in prod, locmem in tests), TTL is short — this guards retries, not long-term
dedup.
"""

from __future__ import annotations

from django.core.cache import cache

_TTL_SECONDS = 120


def _cache_key(api_key, namespace: str, idem_key: str) -> str:
    owner = getattr(api_key, "pk", "anon")
    return f"platform_idem:{owner}:{namespace}:{idem_key}"


def lookup(request, namespace: str):
    """Return ``(cache_key, cached_or_None)``. ``cache_key`` is None if no header."""
    idem_key = request.headers.get("Idempotency-Key")
    if not idem_key:
        return None, None
    ck = _cache_key(getattr(request, "auth", None), namespace, idem_key)
    return ck, cache.get(ck)


def store(cache_key: str | None, status_code: int, data) -> None:
    if cache_key is None:
        return
    cache.set(cache_key, {"status": status_code, "data": data}, _TTL_SECONDS)
