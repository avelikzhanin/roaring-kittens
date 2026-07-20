from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from tinkoff.invest import AsyncClient, CandleInterval
from tinkoff.invest.utils import money_to_decimal, now, quotation_to_decimal

from roaring_kittens.broker.models import Candle, DividendItem, PortfolioSnapshot, Position
from roaring_kittens.utils.retry import retry_async


def map_portfolio(raw, figi_map: dict[str, tuple[str, str]]) -> PortfolioSnapshot:
    """Чистая функция: ответ operations.get_portfolio → PortfolioSnapshot."""
    positions = []
    for p in raw.positions:
        if p.instrument_type != "share":
            continue
        ticker, name = figi_map.get(p.figi, (p.figi, p.figi))
        avg = money_to_decimal(p.average_position_price)
        cur = money_to_decimal(p.current_price)
        pnl = ((cur - avg) / avg * 100).quantize(Decimal("0.1"), ROUND_HALF_UP) if avg else Decimal("0")
        positions.append(Position(
            ticker=ticker, name=name, figi=p.figi,
            quantity=quotation_to_decimal(p.quantity),
            avg_price=avg, current_price=cur, pnl_pct=pnl,
        ))
    return PortfolioSnapshot(
        total_value=money_to_decimal(raw.total_amount_portfolio),
        positions=sorted(positions, key=lambda x: x.ticker),
    )


def map_last_prices(resp) -> dict[str, Decimal]:
    """Чистая функция: ответ get_last_prices -> figi->цена."""
    return {p.figi: quotation_to_decimal(p.price) for p in resp.last_prices}


class TinkoffBroker:
    def __init__(self, token: str):
        self._token = token
        self._figi_map: dict[str, tuple[str, str]] | None = None

    async def _ensure_figi_map(self, client) -> dict[str, tuple[str, str]]:
        if self._figi_map is None:
            resp = await client.instruments.shares()
            self._figi_map = {s.figi: (s.ticker, s.name) for s in resp.instruments}
        return self._figi_map

    @retry_async(attempts=3, base_delay=1.0)
    async def get_portfolio(self) -> PortfolioSnapshot:
        async with AsyncClient(self._token) as client:
            figi_map = await self._ensure_figi_map(client)
            accounts = await client.users.get_accounts()
            raw = await client.operations.get_portfolio(account_id=accounts.accounts[0].id)
            return map_portfolio(raw, figi_map)

    @retry_async(attempts=3, base_delay=1.0)
    async def get_daily_candles(self, figi: str, days: int = 35) -> list[Candle]:
        async with AsyncClient(self._token) as client:
            resp = await client.market_data.get_candles(
                figi=figi, from_=now() - timedelta(days=days), to=now(),
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            )
            return [
                Candle(
                    day=c.time.date(),
                    open=quotation_to_decimal(c.open), close=quotation_to_decimal(c.close),
                    high=quotation_to_decimal(c.high), low=quotation_to_decimal(c.low),
                    volume=c.volume,
                )
                for c in resp.candles if c.is_complete
            ]

    @retry_async(attempts=3, base_delay=1.0)
    async def get_dividends(self, figi: str, years_back: int = 3) -> list[DividendItem]:
        async with AsyncClient(self._token) as client:
            resp = await client.instruments.get_dividends(
                figi=figi,
                from_=now() - timedelta(days=365 * years_back),
                to=now() + timedelta(days=365),  # включая объявленные будущие
            )
            return [
                DividendItem(
                    # SDK превращает незаданный protobuf-Timestamp в epoch(1970) —
                    # None он не бывает никогда, поэтому фильтруем по году.
                    payment_date=(d.payment_date.date()
                                  if d.payment_date and d.payment_date.year > 1970
                                  else None),
                    amount=money_to_decimal(d.dividend_net),
                )
                for d in resp.dividends
            ]

    @retry_async(attempts=3, base_delay=1.0)
    async def get_last_prices(self, figis: list[str]) -> dict[str, Decimal]:
        if not figis:
            return {}
        async with AsyncClient(self._token) as client:
            resp = await client.market_data.get_last_prices(figi=figis)
            return map_last_prices(resp)

    async def list_shares(self) -> dict[str, tuple[str, str]]:
        """ticker -> (figi, name) для маппинга universe."""
        async with AsyncClient(self._token) as client:
            resp = await client.instruments.shares()
            return {s.ticker: (s.figi, s.name) for s in resp.instruments
                    if s.class_code == "TQBR"}
