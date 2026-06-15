from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import Candle

MIN_CANDLES = 8


@dataclass(frozen=True)
class TechSummary:
    last_close: Decimal
    change_1d_pct: Decimal
    change_7d_pct: Decimal
    change_30d_pct: Decimal
    high_30d: Decimal
    low_30d: Decimal

    def as_text(self) -> str:
        return (
            f"Последняя цена: {self.last_close} ₽. "
            f"Изменение: 1д {self.change_1d_pct:+}%, 7д {self.change_7d_pct:+}%, "
            f"30д {self.change_30d_pct:+}%. "
            f"Диапазон 30д: {self.low_30d}–{self.high_30d} ₽."
        )


def _pct(cur: Decimal, prev: Decimal) -> Decimal:
    if not prev:
        return Decimal("0")
    return ((cur - prev) / prev * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def compute_tech_summary(candles: list[Candle]) -> TechSummary | None:
    if len(candles) < MIN_CANDLES:
        return None
    candles = sorted(candles, key=lambda c: c.day)
    last30 = candles[-30:]
    closes = [c.close for c in last30]
    last = closes[-1]
    return TechSummary(
        last_close=last,
        change_1d_pct=_pct(last, closes[-2]),
        change_7d_pct=_pct(last, closes[-6] if len(closes) >= 6 else closes[0]),
        change_30d_pct=_pct(last, closes[0]),
        high_30d=max(c.high for c in last30),
        low_30d=min(c.low for c in last30),
    )
