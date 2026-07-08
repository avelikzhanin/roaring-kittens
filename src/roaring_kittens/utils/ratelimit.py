from datetime import date, datetime, timezone


class DailyLimiter:
    """In-memory дневной лимит на пользователя. Сбрасывается рестартом процесса — ок для pet."""

    def __init__(self, limit: int):
        self.limit = limit
        self._counts: dict[int, tuple[date, int]] = {}

    def allow(self, user_id: int) -> bool:
        today = datetime.now(tz=timezone.utc).date()
        day, count = self._counts.get(user_id, (today, 0))
        if day != today:
            day, count = today, 0
        if count >= self.limit:
            self._counts[user_id] = (day, count)
            return False
        self._counts[user_id] = (day, count + 1)
        return True
