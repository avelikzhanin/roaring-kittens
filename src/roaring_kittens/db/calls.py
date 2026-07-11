from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import Date, cast, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import call_scores, calls


@dataclass(frozen=True)
class CallRecord:
    id: UUIDType
    created_at: datetime
    asked_by: int
    ticker: str
    figi: str
    source: str
    question: str | None
    stance: str
    confidence: float
    summary: str
    price_at_call: Decimal | None
    news_urls: list[str]


@dataclass(frozen=True)
class ScoredCall:
    ticker: str
    stance: str
    created_at: datetime
    source: str
    horizon_days: int
    stock_return_pct: Decimal
    imoex_return_pct: Decimal
    verdict: str

    @property
    def excess_pp(self) -> Decimal:
        return self.stock_return_pct - self.imoex_return_pct


def _row_to_call(r) -> CallRecord:
    return CallRecord(id=r.id, created_at=r.created_at, asked_by=r.asked_by,
                      ticker=r.ticker, figi=r.figi, source=r.source, question=r.question,
                      stance=r.stance, confidence=r.confidence, summary=r.summary,
                      price_at_call=r.price_at_call, news_urls=list(r.news_urls))


async def save_call(session: AsyncSession, *, asked_by: int, ticker: str, figi: str,
                    source: str, question: str | None, stance: str, confidence: float,
                    summary: str, price_at_call: Decimal | None, news_urls: list[str],
                    created_at: datetime | None = None) -> UUIDType:
    values = dict(asked_by=asked_by, ticker=ticker, figi=figi, source=source,
                  question=question, stance=stance, confidence=confidence,
                  summary=summary, price_at_call=price_at_call, news_urls=news_urls)
    if created_at is not None:  # retro-посев пишет прошлую дату
        values["created_at"] = created_at
    result = await session.execute(calls.insert().values(**values).returning(calls.c.id))
    return result.scalar_one()


async def get_last_call(session: AsyncSession, ticker: str,
                        within_days: int = 7) -> CallRecord | None:
    since = datetime.now(tz=timezone.utc) - timedelta(days=within_days)
    row = (await session.execute(
        select(calls).where(calls.c.ticker == ticker, calls.c.created_at >= since)
        .order_by(calls.c.created_at.desc()).limit(1))).first()
    return _row_to_call(row) if row else None


async def get_unscored_calls(session: AsyncSession, horizon_days: int,
                             now: datetime) -> list[CallRecord]:
    cutoff = now - timedelta(days=horizon_days)
    already = exists(select(1).where(call_scores.c.call_id == calls.c.id,
                                     call_scores.c.horizon_days == horizon_days))
    rows = (await session.execute(
        select(calls).where(calls.c.created_at <= cutoff,
                            calls.c.price_at_call.isnot(None), ~already))).fetchall()
    return [_row_to_call(r) for r in rows]


async def save_score(session: AsyncSession, call_id: UUIDType, horizon_days: int,
                     stock_return_pct: Decimal, imoex_return_pct: Decimal,
                     verdict: str) -> None:
    stmt = insert(call_scores).values(
        call_id=call_id, horizon_days=horizon_days, stock_return_pct=stock_return_pct,
        imoex_return_pct=imoex_return_pct, verdict=verdict,
    ).on_conflict_do_nothing(index_elements=["call_id", "horizon_days"])
    await session.execute(stmt)


async def get_scored_calls(session: AsyncSession) -> list[ScoredCall]:
    j = calls.join(call_scores, calls.c.id == call_scores.c.call_id)
    rows = (await session.execute(
        select(calls.c.ticker, calls.c.stance, calls.c.created_at, calls.c.source,
               call_scores.c.horizon_days, call_scores.c.stock_return_pct,
               call_scores.c.imoex_return_pct, call_scores.c.verdict)
        .select_from(j))).fetchall()
    return [ScoredCall(*r) for r in rows]


async def count_calls_by_source(session: AsyncSession, source: str) -> int:
    return (await session.execute(
        select(func.count()).where(calls.c.source == source))).scalar_one()


async def count_unscored(session: AsyncSession) -> int:
    """Скорибельные вызовы без единой оценки (NULL-price не считаем — они не зреют)."""
    any_score = exists(select(1).where(call_scores.c.call_id == calls.c.id))
    return (await session.execute(
        select(func.count()).select_from(calls)
        .where(~any_score, calls.c.price_at_call.isnot(None)))).scalar_one()


async def get_retro_seeded_keys(session: AsyncSession) -> set[tuple[str, date]]:
    """(ticker, дата as-of) уже посеянных retro-вызовов — для идемпотентного /seed_retro."""
    rows = (await session.execute(
        select(calls.c.ticker, cast(calls.c.created_at, Date))
        .where(calls.c.source == "retro"))).fetchall()
    return {(r[0], r[1]) for r in rows}
