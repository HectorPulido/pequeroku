from __future__ import annotations
from django.conf import settings
import redis.asyncio as redis

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


KEY_FMT = "{redis_prefix}:fsrev:{cid}:{path}"


class VersionStore:
    @staticmethod
    async def get_rev(cid: str, path: str) -> int:
        r = _get_client()
        v = await r.get(
            KEY_FMT.format(cid=cid, path=path, redis_prefix=settings.REDIS_PREFIX)
        )
        return int(v or 0)

    @staticmethod
    async def bump_rev(cid: str, path: str) -> int:
        r = _get_client()
        # INCR crea la clave si no existe
        return int(
            await r.incr(
                KEY_FMT.format(cid=cid, path=path, redis_prefix=settings.REDIS_PREFIX)
            )
        )

    @staticmethod
    async def reset_path(cid: str, path: str) -> None:
        r = _get_client()
        await r.delete(
            KEY_FMT.format(cid=cid, path=path, redis_prefix=settings.REDIS_PREFIX)
        )
