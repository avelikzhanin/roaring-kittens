import asyncio
import functools

import structlog

log = structlog.get_logger()


def retry_async(attempts: int = 3, base_delay: float = 1.0,
                exceptions: tuple[type[Exception], ...] = (Exception,)):
    """Экспоненциальный backoff: base_delay * 2^attempt."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            for attempt in range(attempts):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    log.warning("retry", fn=fn.__name__, attempt=attempt + 1,
                                delay=delay, error=str(exc))
                    await asyncio.sleep(delay)
        return wrapper
    return decorator
