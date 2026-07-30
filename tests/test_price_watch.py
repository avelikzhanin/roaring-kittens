from datetime import date
from decimal import Decimal

from roaring_kittens.price_watch import (
    DayMoveDeduper, DealSignalDeduper, significant_move,
)


def test_deal_signal_deduper_per_kind():
    d = DealSignalDeduper()
    today = date(2026, 7, 30)
    assert d.seen("id1", "exit", today) is False
    d.mark("id1", "exit", today)
    assert d.seen("id1", "exit", today) is True
    assert d.seen("id1", "target", today) is False   # другой тип — отдельно
    d.purge(date(2026, 7, 31))
    assert d.seen("id1", "exit", today) is False


def test_significant_move_threshold():
    assert significant_move(Decimal("100"), Decimal("94.9")) == Decimal("-5.1")
    assert significant_move(Decimal("100"), Decimal("105.0")) == Decimal("5.0")
    assert significant_move(Decimal("100"), Decimal("104.9")) is None   # < 5%
    assert significant_move(Decimal("0"), Decimal("100")) is None       # нет базы


def test_deduper_seen_mark_and_purge():
    d = DayMoveDeduper()
    today, tomorrow = date(2026, 7, 18), date(2026, 7, 19)
    assert d.seen(42, "SBER", today) is False   # проверка без пометки
    assert d.seen(42, "SBER", today) is False   # повторная проверка не пометила
    d.mark(42, "SBER", today)                    # пометка только после успешной отправки
    assert d.seen(42, "SBER", today) is True
    assert d.seen(777, "SBER", today) is False   # у другого юзера свой дедуп
    assert d.seen(42, "GAZP", today) is False
    assert d.seen(42, "SBER", tomorrow) is False  # новый день — можно снова
    d.purge(tomorrow)                             # вчерашние ключи выброшены
    assert d.seen(42, "SBER", today) is False
