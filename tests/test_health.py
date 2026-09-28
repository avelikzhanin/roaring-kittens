from datetime import datetime, timedelta, timezone

from roaring_kittens.health import DependencyHealth, track

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def test_down_only_after_threshold_without_success():
    h = DependencyHealth(threshold=timedelta(hours=1))
    assert h.is_down(now=T0) is False                  # ничего не знаем — не паникуем
    h.note_failure("tls", now=T0)
    assert h.is_down(now=T0 + timedelta(minutes=30)) is False  # порог не вышел
    h.note_failure("tls", now=T0 + timedelta(minutes=61))
    assert h.is_down(now=T0 + timedelta(minutes=61)) is True   # час сбоев без успеха
    assert h.last_error == "tls"


def test_success_resets_down_and_tracks_down_since():
    h = DependencyHealth(threshold=timedelta(hours=1))
    h.note_success(now=T0)
    h.note_failure("x", now=T0 + timedelta(minutes=10))
    h.note_failure("x", now=T0 + timedelta(hours=2))
    assert h.is_down(now=T0 + timedelta(hours=2)) is True
    assert h.down_since == T0 + timedelta(minutes=10)     # первый сбой после успеха
    h.note_success(now=T0 + timedelta(hours=3))
    assert h.is_down(now=T0 + timedelta(hours=3)) is False
    assert h.down_since is None


def test_alert_dedup_is_per_episode_not_per_day():
    h = DependencyHealth(threshold=timedelta(hours=1))
    h.note_failure("x", now=T0)
    assert h.needs_alert("2026-09-01") is True
    h.mark_alerted("2026-09-01")
    assert h.needs_alert("2026-09-01") is False          # тот же эпизод, тот же день
    h.note_success(now=T0 + timedelta(hours=2))          # ожил
    h.mark_recovered()
    h.note_failure("x", now=T0 + timedelta(hours=3))     # упал снова в тот же день
    assert h.needs_alert("2026-09-01") is True           # новый эпизод — не молчим
    h.mark_alerted("2026-09-01")
    assert h.needs_alert("2026-09-02") is True           # сменился день — напоминаем


async def test_track_writes_only_when_instance_has_health():
    class Broker:
        def __init__(self, health):
            self._health = health

        @track
        async def call(self, ok: bool):
            if not ok:
                raise RuntimeError("boom")
            return "fine"

    h = DependencyHealth(threshold=timedelta(0))
    tracked, silent = Broker(h), Broker(None)
    assert await tracked.call(True) == "fine" and h.last_ok is not None
    try:
        await tracked.call(False)
    except RuntimeError:
        pass
    assert h.is_down() is True and h.last_error == "boom"
    try:
        await silent.call(False)   # юзерский брокер без пульса — ничего не пишет
    except RuntimeError:
        pass
    assert h.last_error == "boom"
