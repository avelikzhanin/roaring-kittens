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
    """In-memory скользящее окно: не больше max_per_hour несрочных алертов."""

    def __init__(self, max_per_hour: int = 3):
        self.max_per_hour = max_per_hour
        self._sent: deque[datetime] = deque()

    def allow(self, now: datetime) -> bool:
        hour_ago = now - timedelta(hours=1)
        while self._sent and self._sent[0] <= hour_ago:
            self._sent.popleft()
        if len(self._sent) >= self.max_per_hour:
            return False
        self._sent.append(now)
        return True


def _now_local(deps) -> datetime:
    return datetime.now(tz=ZoneInfo(deps.settings.tz))


async def send_alert(deps, bot, chat_id: int, text: str, *,
                     critical: bool = False, keyboard=None) -> str:
    """Возвращает 'sent' | 'buffered'. Буферизованные приходят с утренним дайджестом
    (кнопки при буферизации теряются — сохраняется только текст)."""
    now = _now_local(deps)
    if not critical:
        if is_quiet_hours(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_quiet", chat_id=chat_id)
            return "buffered"
        if not deps.alert_throttle.allow(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_throttle", chat_id=chat_id)
            return "buffered"
    await bot.send_message(chat_id, text, reply_markup=keyboard)
    return "sent"
