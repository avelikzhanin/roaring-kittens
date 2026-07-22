"""Единый роутер алертов: quiet hours 22:00-08:00 МСК -> ночной буфер,
троттлинг <=3/час -> буфер, critical -> сквозь всё."""
from collections import deque
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog

from roaring_kittens.db.alerts_buffer import push_alert

log = structlog.get_logger()

QUIET_START = time(22, 0)
QUIET_END = time(8, 0)


def is_quiet_hours(now_local: datetime) -> bool:
    t = now_local.time()
    return t >= QUIET_START or t < QUIET_END


class AlertThrottle:
    """In-memory скользящее окно: не больше max_per_hour несрочных алертов.

    would_allow/record разделены: слот занимается ПОСЛЕ успешной отправки,
    чтобы сбой Telegram не сжигал лимит."""

    def __init__(self, max_per_hour: int = 3):
        self.max_per_hour = max_per_hour
        self._sent: deque[datetime] = deque()

    def _evict(self, now: datetime) -> None:
        hour_ago = now - timedelta(hours=1)
        while self._sent and self._sent[0] <= hour_ago:
            self._sent.popleft()

    def would_allow(self, now: datetime) -> bool:
        self._evict(now)
        return len(self._sent) < self.max_per_hour

    def record(self, now: datetime) -> None:
        self._evict(now)
        self._sent.append(now)

    def allow(self, now: datetime) -> bool:
        """Проверка+запись одним вызовом (для простых сценариев/тестов)."""
        if not self.would_allow(now):
            return False
        self.record(now)
        return True


def _now_local(deps) -> datetime:
    return datetime.now(tz=ZoneInfo(deps.settings.tz))


async def send_alert(deps, bot, chat_id: int, text: str, *,
                     critical: bool = False, keyboard=None) -> str:
    """Возвращает 'sent' | 'buffered'. Буферизованные приходят с утренним дайджестом
    (кнопки при буферизации теряются — сохраняется только текст)."""
    now = _now_local(deps)
    throttle = deps.alert_throttles.setdefault(chat_id, AlertThrottle())
    if not critical:
        if is_quiet_hours(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_quiet", chat_id=chat_id)
            return "buffered"
        if not throttle.would_allow(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_throttle", chat_id=chat_id)
            return "buffered"
    await bot.send_message(chat_id, text, reply_markup=keyboard)
    if not critical:
        throttle.record(now)  # слот занимаем только после успешной отправки
    return "sent"
