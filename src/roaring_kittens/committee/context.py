from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog

from roaring_kittens.broker.fundamentals import format_dividend_summary
from roaring_kittens.broker.position_note import (
    position_note_from_snapshot, position_weight_pct,
)
from roaring_kittens.broker.tech import (
    Indicators, TechSummary, compute_indicators, compute_tech_summary,
)
from roaring_kittens.db.calls import get_last_call
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()

NEWS_WINDOW_DAYS = 7
CANDLES_DAYS = 90
CROWD_SOURCES = {"smartlab"}


@dataclass
class CouncilContext:
    ticker: str
    tech: TechSummary | None
    indicators: Indicators
    news_facts: list[NewsItem]
    crowd_posts: list[NewsItem]
    dividend_summary: str
    position_note: str | None          # None => спрашивал не владелец
    position_weight_pct: Decimal | None
    prev_call_note: str | None


async def build_council_context(deps, instrument: Instrument, asked_by: int,
                                today: date) -> CouncilContext:
    candles = await deps.broker.get_daily_candles(instrument.figi, days=CANDLES_DAYS)
    tech = compute_tech_summary(candles)
    indicators = compute_indicators(candles)

    since = datetime.now(tz=timezone.utc) - timedelta(days=NEWS_WINDOW_DAYS)
    async with deps.session_factory() as session:
        news = await get_news_for_tickers(session, [instrument.ticker], since=since)
        prev = await get_last_call(session, instrument.ticker)
    facts = [n for n in news if n.source not in CROWD_SOURCES]
    crowd = [n for n in news if n.source in CROWD_SOURCES]

    try:
        divs = await deps.broker.get_dividends(instrument.figi)
    except Exception as exc:
        log.warning("dividends_failed", ticker=instrument.ticker, error=str(exc))
        divs = []
    dividend_summary = format_dividend_summary(
        divs, tech.last_close if tech else None, today=today)

    position_note, weight = None, None
    owner_id = await fetch_owner_id(deps.session_factory)
    if asked_by == owner_id:
        try:
            snap = await deps.broker.get_portfolio()
            position_note = position_note_from_snapshot(snap, instrument.ticker)
            weight = position_weight_pct(snap, instrument.ticker)
        except Exception as exc:
            log.warning("council_position_failed", error=str(exc))

    prev_note = None
    if prev:
        days = (datetime.now(tz=timezone.utc) - prev.created_at).days
        prev_note = (f"Прошлый разбор бота ({days} дн назад): "
                     f"{prev.stance} {round(prev.confidence * 100)}%")

    return CouncilContext(ticker=instrument.ticker, tech=tech, indicators=indicators,
                          news_facts=facts, crowd_posts=crowd,
                          dividend_summary=dividend_summary,
                          position_note=position_note, position_weight_pct=weight,
                          prev_call_note=prev_note)
