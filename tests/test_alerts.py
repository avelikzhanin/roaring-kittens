from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import roaring_kittens.alerts as alerts_mod
from roaring_kittens.alerts import AlertThrottle, is_quiet_hours, send_alert

MSK = ZoneInfo("Europe/Moscow")


def _msk(h, m=0):
    return datetime(2026, 7, 18, h, m, tzinfo=MSK)


def test_quiet_hours_boundaries():
    assert is_quiet_hours(_msk(21, 59)) is False
    assert is_quiet_hours(_msk(22, 0)) is True
    assert is_quiet_hours(_msk(3)) is True
    assert is_quiet_hours(_msk(7, 59)) is True
    assert is_quiet_hours(_msk(8, 0)) is False
    assert is_quiet_hours(_msk(12)) is False


def test_throttle_three_per_hour_sliding():
    t = AlertThrottle(max_per_hour=3)
    base = _msk(12)
    assert t.allow(base) and t.allow(base) and t.allow(base)
    assert t.allow(base + timedelta(minutes=10)) is False       # 4-й в окне
    assert t.allow(base + timedelta(minutes=61)) is True        # окно уехало


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


def _deps(now_msk):
    return SimpleNamespace(
        settings=SimpleNamespace(tz="Europe/Moscow"),
        session_factory=lambda: FakeSession(),
        alert_throttle=AlertThrottle(max_per_hour=3),
        _now=now_msk,  # для подмены времени в тесте
    )


async def test_send_alert_routing(monkeypatch):
    pushed = []

    async def fake_push(session, chat_id, payload):
        pushed.append(payload)

    monkeypatch.setattr(alerts_mod, "push_alert", fake_push)
    bot = SimpleNamespace(send_message=AsyncMock())

    day = _deps(_msk(12))
    monkeypatch.setattr(alerts_mod, "_now_local", lambda deps: deps._now)
    # днём — шлётся
    assert await send_alert(day, bot, 42, "текст") == "sent"
    bot.send_message.assert_awaited_once()
    # 3/час: 2-й и 3-й ок, 4-й — в буфер
    assert await send_alert(day, bot, 42, "т2") == "sent"
    assert await send_alert(day, bot, 42, "т3") == "sent"
    assert await send_alert(day, bot, 42, "т4") == "buffered"
    assert pushed == ["т4"]
    # ночь: буферится, critical — сквозь
    night = _deps(_msk(23))
    assert await send_alert(night, bot, 42, "ночной") == "buffered"
    assert await send_alert(night, bot, 42, "critical!", critical=True) == "sent"
    assert pushed == ["т4", "ночной"]
