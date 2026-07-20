"""Дневной прайс-алерт: |движение от вчерашнего закрытия| >= 5% — раз в день на тикер."""
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog

from roaring_kittens.alerts import send_alert
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import get_active_theses
from roaring_kittens.db.watchlist import list_watchlist
from roaring_kittens.telegram.formatting import esc

log = structlog.get_logger()

DAY_MOVE_THRESHOLD_PP = Decimal("5")


def significant_move(prev_close: Decimal, last: Decimal) -> Decimal | None:
    if not prev_close:
        return None
    move = ((last - prev_close) / prev_close * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)
    return move if abs(move) >= DAY_MOVE_THRESHOLD_PP else None


class DayMoveDeduper:
    """Один алерт на тикер в день (in-memory, сброс при рестарте допустим)."""

    def __init__(self):
        self._seen: set[tuple[date, str]] = set()

    def allow(self, ticker: str, today: date) -> bool:
        key = (today, ticker)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


_deduper = DayMoveDeduper()
_prev_close_cache: dict[tuple[date, str], Decimal] = {}


async def _prev_close(deps, figi: str, today: date) -> Decimal | None:
    key = (today, figi)
    if key not in _prev_close_cache:
        try:
            candles = await deps.broker.get_daily_candles(figi, days=10)
        except Exception as exc:
            log.warning("price_watch_candles_failed", figi=figi, error=str(exc))
            return None
        done = sorted(candles, key=lambda c: c.day)
        if not done:
            return None
        _prev_close_cache[key] = done[-1].close  # последняя ЗАВЕРШЁННАЯ сессия
    return _prev_close_cache[key]


async def price_watch_job(deps, bot) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    figi_by_ticker: dict[str, str] = {}
    try:
        snap = await deps.broker.get_portfolio()
        for p in snap.positions:
            figi_by_ticker[p.ticker] = p.figi
    except Exception as exc:
        log.warning("price_watch_portfolio_failed", error=str(exc))
    async with deps.session_factory() as session:
        watched = await list_watchlist(session, owner_id)
        theses = await get_active_theses(session)
    for t in watched:
        instr = deps.universe.get(t)
        if instr:
            figi_by_ticker.setdefault(t, instr.figi)
    for th in theses:
        figi_by_ticker.setdefault(th.ticker, th.figi)
    if not figi_by_ticker:
        return
    try:
        prices = await deps.broker.get_last_prices(list(figi_by_ticker.values()))
    except Exception as exc:
        log.error("price_watch_last_prices_failed", error=str(exc))
        return
    today = datetime.now(tz=timezone.utc).date()
    for ticker, figi in figi_by_ticker.items():
        last = prices.get(figi)
        if last is None:
            continue
        prev = await _prev_close(deps, figi, today)
        if prev is None:
            continue
        move = significant_move(prev, last)
        if move is None or not _deduper.allow(ticker, today):
            continue
        arrow = "📈" if move > 0 else "📉"
        await send_alert(
            deps, bot, owner_id,
            f"{arrow} <b>{ticker}</b> {'+' if move > 0 else '−'}{abs(move)}% за день "
            f"({esc(str(prev))} → {esc(str(last))} ₽). Разбор: /council {ticker}")
    log.info("price_watch_done", tickers=len(figi_by_ticker))
