"""Пульс внешних зависимостей: бесшумная деградация запрещена (инцидент 09.2026 —
Tinkoff TLS падал месяц, а бот показывал застывший портфель)."""
import functools
from datetime import datetime, timedelta, timezone


class DependencyHealth:
    def __init__(self, threshold: timedelta = timedelta(hours=1)):
        self.threshold = threshold
        self.last_ok: datetime | None = None
        self.down_since: datetime | None = None   # первый сбой после последнего успеха
        self.last_error: str | None = None
        self.alerted_for: datetime | None = None  # down_since эпизода, о котором сообщили
        self.alerted_on: str | None = None        # 'YYYY-MM-DD' последнего 🩺 (tz настроек)
        self.recovery_pending = False             # алерт был -> при успехе шлём ✅

    def note_success(self, now: datetime | None = None) -> None:
        self.last_ok = now or datetime.now(tz=timezone.utc)
        self.down_since = None
        self.last_error = None

    def note_failure(self, error: str, now: datetime | None = None) -> None:
        now = now or datetime.now(tz=timezone.utc)
        if self.down_since is None:
            self.down_since = now
        self.last_error = error[:300]

    def is_down(self, now: datetime | None = None) -> bool:
        if self.down_since is None:
            return False
        now = now or datetime.now(tz=timezone.utc)
        return now - self.down_since >= self.threshold

    def needs_alert(self, today: str) -> bool:
        """🩺 нужен, если эпизод падения новый ИЛИ сменился календарный день —
        дедуп по эпизоду, а не по дате: после ✅ повторное падение не молчит."""
        return self.alerted_for != self.down_since or self.alerted_on != today

    def mark_alerted(self, today: str) -> None:
        self.alerted_for = self.down_since
        self.alerted_on = today
        self.recovery_pending = True

    def mark_recovered(self) -> None:
        self.alerted_for = None
        self.alerted_on = None
        self.recovery_pending = False


tinkoff = DependencyHealth()


def track(method):
    """Декоратор метода брокера: пульс пишется в self._health (None — молчим).
    Юзерские брокеры создаются без пульса: отозванный токен друга — не «Tinkoff упал»."""
    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        dep = getattr(self, "_health", None)
        try:
            result = await method(self, *args, **kwargs)
        except Exception as exc:
            if dep is not None:
                dep.note_failure(str(exc))
            raise
        if dep is not None:
            dep.note_success()
        return result
    return wrapper
