from datetime import date
from decimal import Decimal

from roaring_kittens.price_watch import DayMoveDeduper, significant_move


def test_significant_move_threshold():
    assert significant_move(Decimal("100"), Decimal("94.9")) == Decimal("-5.1")
    assert significant_move(Decimal("100"), Decimal("105.0")) == Decimal("5.0")
    assert significant_move(Decimal("100"), Decimal("104.9")) is None   # < 5%
    assert significant_move(Decimal("0"), Decimal("100")) is None       # нет базы


def test_deduper_once_per_day():
    d = DayMoveDeduper()
    today, tomorrow = date(2026, 7, 18), date(2026, 7, 19)
    assert d.allow("SBER", today) is True
    assert d.allow("SBER", today) is False
    assert d.allow("GAZP", today) is True
    assert d.allow("SBER", tomorrow) is True  # новый день — можно снова
