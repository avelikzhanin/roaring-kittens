from datetime import date
from decimal import Decimal

from roaring_kittens.broker.fundamentals import format_dividend_summary
from roaring_kittens.broker.models import DividendItem

TODAY = date(2026, 7, 12)


def test_no_dividends():
    text = format_dividend_summary([], last_close=Decimal("300"), today=TODAY)
    assert "не выплачивались" in text


def test_summary_with_yield_excludes_future_from_12m_sum():
    items = [
        DividendItem(payment_date=date(2025, 12, 10), amount=Decimal("15")),
        DividendItem(payment_date=date(2026, 6, 20), amount=Decimal("18")),
        DividendItem(payment_date=date(2026, 9, 20), amount=Decimal("20")),  # ОБЪЯВЛЕН, будущее
        DividendItem(payment_date=date(2023, 5, 1), amount=Decimal("10")),   # старше 12 мес
    ]
    text = format_dividend_summary(items, last_close=Decimal("300"), today=TODAY)
    assert "18 ₽" in text and "15 ₽" in text
    # за 12 мес ВЫПЛАЧЕНО: 15+18=33 (будущие 20 ₽ не считаются); 33/300*100 = 11.0%
    assert "33" in text and "11.0%" in text
    assert "Объявлено" in text and "20 ₽" in text  # будущая выплата показана отдельно


def test_summary_without_price_skips_yield():
    items = [DividendItem(payment_date=date(2026, 6, 20), amount=Decimal("18"))]
    text = format_dividend_summary(items, last_close=None, today=TODAY)
    assert "%" not in text


def test_only_announced_future_dividend():
    items = [DividendItem(payment_date=date(2026, 9, 20), amount=Decimal("20"))]
    text = format_dividend_summary(items, last_close=Decimal("300"), today=TODAY)
    assert "Объявлено" in text and "не выплачивались" not in text
