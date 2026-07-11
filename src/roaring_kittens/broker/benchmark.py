"""Бенчмарк IMOEX: дневные свечи индекса из публичного MOEX ISS (без auth)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx
import structlog

from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()

IMOEX_CANDLES_URL = ("https://iss.moex.com/iss/engines/stock/markets/index/"
                     "securities/IMOEX/candles.json?interval=24&from={frm}&till={till}")


def parse_iss_candles(payload: dict) -> list[tuple[date, Decimal]]:
    block = payload["candles"]
    ci, bi = block["columns"].index("close"), block["columns"].index("begin")
    out = []
    for row in block["data"]:
        d = datetime.strptime(str(row[bi])[:10], "%Y-%m-%d").date()
        out.append((d, Decimal(str(row[ci]))))
    return sorted(out)


@retry_async(attempts=2, base_delay=2.0)
async def fetch_imoex_closes(frm: date, till: date,
                             transport: httpx.BaseTransport | None = None
                             ) -> list[tuple[date, Decimal]]:
    url = IMOEX_CANDLES_URL.format(frm=frm.isoformat(), till=till.isoformat())
    async with httpx.AsyncClient(transport=transport, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_iss_candles(resp.json())


def return_between(closes: list[tuple[date, Decimal]], start: date,
                   end: date) -> Decimal | None:
    """Доходность %, ближайший торговый день >= start до ближайшего <= end.

    Требует ВОЗРАСТАЮЩЕЙ сортировки closes (parse_iss_candles сортирует;
    свечи брокера сортирует вызывающий — API-порядку не доверяем).
    """
    start_close = next((c for d, c in closes if d >= start), None)
    end_close = next((c for d, c in reversed(closes) if d <= end), None)
    if start_close is None or end_close is None or not start_close:
        return None
    start_day = next(d for d, c in closes if d >= start)
    end_day = next(d for d, c in reversed(closes) if d <= end)
    if end_day < start_day:
        return None
    return ((end_close - start_close) / start_close * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)
