from datetime import date
from decimal import Decimal

import httpx

from roaring_kittens.broker.benchmark import (
    fetch_imoex_closes, parse_iss_candles, return_between,
)

ISS_CANDLES = {
    "candles": {
        "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
        "data": [
            [3000, 3010.5, 3020, 2990, 0, 0, "2026-06-01 00:00:00", "2026-06-01 23:59:59"],
            [3010, 3050.0, 3060, 3000, 0, 0, "2026-06-02 00:00:00", "2026-06-02 23:59:59"],
            [3050, 3100.0, 3110, 3040, 0, 0, "2026-06-05 00:00:00", "2026-06-05 23:59:59"],
        ],
    }
}


def test_parse_iss_candles():
    closes = parse_iss_candles(ISS_CANDLES)
    assert closes[0] == (date(2026, 6, 1), Decimal("3010.5"))
    assert len(closes) == 3


def test_return_between_uses_nearest_trading_days():
    closes = parse_iss_candles(ISS_CANDLES)
    # (3100 - 3010.5) / 3010.5 * 100 = 2.97% -> 3.0
    assert return_between(closes, date(2026, 6, 1), date(2026, 6, 5)) == Decimal("3.0")
    # start 06-03 (выходной) -> ближайший ПОСЛЕ = 06-05; end 06-10 -> ближайший ДО = 06-05
    assert return_between(closes, date(2026, 6, 3), date(2026, 6, 10)) == Decimal("0.0")
    assert return_between(closes, date(2026, 7, 1), date(2026, 7, 10)) is None  # нет данных


async def test_fetch_imoex_closes_via_transport():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=ISS_CANDLES))
    closes = await fetch_imoex_closes(date(2026, 6, 1), date(2026, 6, 10), transport=transport)
    assert len(closes) == 3
