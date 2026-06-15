from datetime import date, timedelta
from decimal import Decimal

from roaring_kittens.broker.models import Candle
from roaring_kittens.broker.tech import compute_tech_summary


def _candles(closes: list[int]) -> list[Candle]:
    start = date(2026, 5, 1)
    return [
        Candle(day=start + timedelta(days=i), open=Decimal(c), close=Decimal(c),
               high=Decimal(c + 2), low=Decimal(c - 2), volume=1000)
        for i, c in enumerate(closes)
    ]


def test_summary_changes():
    closes = [100] * 25 + [110, 111, 112, 113, 114, 115]  # 31 свеча, рост в конце
    s = compute_tech_summary(_candles(closes))
    assert s.last_close == Decimal("115")
    assert s.change_1d_pct == Decimal("0.9")    # 115/114
    assert s.change_7d_pct > Decimal("4")        # 115 vs ~110
    assert s.change_30d_pct == Decimal("15.0")   # 115 vs 100
    assert s.high_30d == Decimal("117") and s.low_30d == Decimal("98")


def test_too_few_candles_returns_none():
    assert compute_tech_summary(_candles([100, 101])) is None
