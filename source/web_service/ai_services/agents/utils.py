import time
import asyncio
import functools
from typing import Callable, Any


def retry_on_exception(
    *,
    delays: list[float] | None = None,
    fallback: Any = None,
    logger: Callable[[str], None] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that retries a function on any exception using the supplied delays.

    Parameters
    ----------
    delays: iterable of seconds to wait between retries.
            If ``None`` the default sequence used by the Agent class is applied
            (0.5, 1.0, 2.0, 4.0, 8.0).
    fallback: value to return if **all** attempts fail.
    logger: optional callable that receives a formatted log line.  If omitted,
            ``print`` is used.

    The wrapped function keeps its original signature and return type.
    """
    if delays is None:
        delays = [0.5, 1.0, 2.0, 4.0, 8.0]

    log = logger or print

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            for attempt, pause in enumerate(delays, start=1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 – we want to catch all
                    log(
                        f"[RETRY] {func.__name__} attempt {attempt}/"
                        f"{len(delays)} failed: {exc}"
                    )
                    raise exc
                    if attempt == len(delays):
                        break
                    time.sleep(pause)

            # All retries exhausted
            log(f"[RETRY] {func.__name__} all attempts failed – returning fallback")
            return fallback

        # Async version – works for ``async def`` as well
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                for attempt, pause in enumerate(delays, start=1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        log(
                            f"[RETRY] async {func.__name__} attempt {attempt}/"
                            f"{len(delays)} failed: {exc}"
                        )
                        raise exc
                        if attempt == len(delays):
                            break
                        await asyncio.sleep(pause)

                log(
                    f"[RETRY] async {func.__name__} all attempts failed – returning fallback"
                )
                return fallback

            return async_wrapper
        return wrapper

    return decorator
