from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware

log = structlog.get_logger()


class AllowListMiddleware(BaseMiddleware):
    """Фаза 0-1: единственный пользователь — admin. Чужие апдейты молча дропаем."""

    def __init__(self, allowed_ids: set[int]):
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in self.allowed_ids:
            log.info("update_dropped", user_id=getattr(user, "id", None))
            return None
        return await handler(event, data)
