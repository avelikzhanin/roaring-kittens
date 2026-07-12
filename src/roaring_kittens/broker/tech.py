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


RSI_PERIOD = 14
VOL_SHORT, VOL_LONG = 5, 30


@dataclass(frozen=True)
class Indicators:
    rsi14: Decimal | None
    ma20: Decimal | None
    ma50: Decimal | None
    volume_ratio: Decimal | None  # средний объём 5д / средний объём 30д

    def as_text(self, last_close: Decimal | None = None) -> str:
        parts = []
        if self.rsi14 is not None:
            parts.append(f"RSI(14): {self.rsi14}")
        if self.ma20 is not None:
            rel = ""
            if last_close is not None:
                rel = " (цена выше)" if last_close > self.ma20 else " (цена ниже)"
            parts.append(f"MA20: {self.ma20}{rel}")
        if self.ma50 is not None:
            rel = ""
            if last_close is not None:
                rel = " (цена выше)" if last_close > self.ma50 else " (цена ниже)"
            parts.append(f"MA50: {self.ma50}{rel}")
        if self.volume_ratio is not None:
            parts.append(f"Объём 5д/30д: {self.volume_ratio}×")
        return ". ".join(parts) if parts else "Индикаторов недостаточно."


def _mean(values: list[Decimal]) -> Decimal:
    return (sum(values) / len(values)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def compute_indicators(candles: list[Candle]) -> Indicators:
    candles = sorted(candles, key=lambda c: c.day)
    closes = [c.close for c in candles]
    rsi = ma20 = ma50 = vol_ratio = None
    if len(closes) >= RSI_PERIOD + 1:
        diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - RSI_PERIOD, len(closes))]
        gains = sum(d for d in diffs if d > 0)
        losses = -sum(d for d in diffs if d < 0)
        if gains + losses == 0:
            rsi = Decimal("50.0")
        else:
            rsi = (gains / (gains + losses) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
    if len(closes) >= 20:
        ma20 = _mean(closes[-20:])
    if len(closes) >= 50:
        ma50 = _mean(closes[-50:])
    volumes = [Decimal(c.volume) for c in candles]
    if len(volumes) >= VOL_LONG:
        long_avg = sum(volumes[-VOL_LONG:]) / VOL_LONG
        short_avg = sum(volumes[-VOL_SHORT:]) / VOL_SHORT
        if long_avg:
            vol_ratio = (short_avg / long_avg).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return Indicators(rsi14=rsi, ma20=ma20, ma50=ma50, volume_ratio=vol_ratio)
