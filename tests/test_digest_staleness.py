from datetime import datetime, timedelta, timezone

from roaring_kittens.digest.morning import staleness_verdict

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


def test_fresh_or_unknown_snapshot_is_silent():
    assert staleness_verdict(timedelta(minutes=20), now=NOW) == ("ok", None)
    assert staleness_verdict(None, now=NOW) == ("ok", None)


def test_hours_old_snapshot_gets_banner():
    kind, text = staleness_verdict(timedelta(hours=5), now=NOW)
    assert kind == "banner" and "⚠️" in text and "28.09 04:00" in text  # 01:00 UTC -> МСК


def test_day_old_snapshot_aborts_digest():
    kind, text = staleness_verdict(timedelta(days=3), now=NOW)
    assert kind == "abort" and "3 дн" in text and "25.09" in text
