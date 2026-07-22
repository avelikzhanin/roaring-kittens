from datetime import date
from decimal import Decimal

from roaring_kittens.price_watch import DayMoveDeduper, significant_move


def test_significant_move_threshold():
    assert significant_move(Decimal("100"), Decimal("94.9")) == Decimal("-5.1")
    assert significant_move(Decimal("100"), Decimal("105.0")) == Decimal("5.0")
    assert significant_move(Decimal("100"), Decimal("104.9")) is None   # < 5%
    assert significant_move(Decimal("0"), Decimal("100")) is None       # нет базы


def test_deduper_seen_mark_and_purge():
    d = DayMoveDeduper()
    today, tomorrow = date(2026, 7, 18), date(2026, 7, 19)
    assert d.seen("SBER", today) is False   # проверка без пометки
    assert d.seen("SBER", today) is False   # повторная проверка не пометила
    d.mark("SBER", today)                    # пометка только после успешной отправки
    assert d.seen("SBER", today) is True
    assert d.seen("GAZP", today) is False
    assert d.seen("SBER", tomorrow) is False  # новый день — можно снова
    d.purge(tomorrow)                         # вчерашние ключи выброшены
    assert d.seen("SBER", today) is False
