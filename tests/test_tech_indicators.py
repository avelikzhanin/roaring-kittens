from datetime import date, timedelta
from decimal import Decimal

from roaring_kittens.broker.models import Candle
from roaring_kittens.broker.tech import Indicators, compute_indicators


def _candles(closes, volumes=None):
    start = date(2026, 3, 1)
    volumes = volumes or [1000] * len(closes)
    return [Candle(day=start + timedelta(days=i), open=Decimal(c), close=Decimal(c),
                   high=Decimal(c + 1), low=Decimal(c - 1), volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))]


def test_rsi_extremes():
    rising = _candles(list(range(100, 160)))     # только рост -> RSI 100
    falling = _candles(list(range(160, 100, -1)))
    assert compute_indicators(rising).rsi14 == Decimal("100.0")
    assert compute_indicators(falling).rsi14 == Decimal("0.0")


def test_moving_averages_and_volume_ratio():
    closes = [100] * 55 + [110] * 5  # 60 свечей
    volumes = [1000] * 55 + [3000] * 5
    ind = compute_indicators(_candles(closes, volumes))
    assert ind.ma20 == Decimal("102.5")          # (15*100 + 5*110)/20
    assert ind.ma50 == Decimal("101.0")          # (45*100 + 5*110)/50
    # long_avg по 30 последним = (25*1000 + 5*3000)/30 = 1333.33; 3000/1333.33 = 2.25 -> 2.3
    assert ind.volume_ratio == Decimal("2.3")


def test_insufficient_data_gives_nones():
    ind = compute_indicators(_candles([100, 101, 102]))
    assert ind.rsi14 is None and ind.ma20 is None and ind.ma50 is None
    assert ind.volume_ratio is None


def test_as_text_mentions_available_only():
    ind = Indicators(rsi14=Decimal("43.2"), ma20=Decimal("301.2"), ma50=None,
                     volume_ratio=Decimal("1.3"))
    text = ind.as_text(last_close=Decimal("295"))
    assert "RSI(14): 43.2" in text and "MA20" in text and "MA50" not in text
