from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import Date, and_, cast, exists, func, select
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
    scored_at: datetime | None = None

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
                    created_at: datetime | None = None,
                    embedding: list[float] | None = None) -> UUIDType:
    values = dict(asked_by=asked_by, ticker=ticker, figi=figi, source=source,
                  question=question, stance=stance, confidence=confidence,
                  summary=summary, price_at_call=price_at_call, news_urls=news_urls,
                  embedding=embedding)
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


async def get_scored_calls(session: AsyncSession, *,
                           asked_by: int | None = None) -> list[ScoredCall]:
    """asked_by: скоуп для рефлексии (админ учится на своих); /track — общий (None)."""
    j = calls.join(call_scores, calls.c.id == call_scores.c.call_id)
    stmt = select(calls.c.ticker, calls.c.stance, calls.c.created_at, calls.c.source,
                  call_scores.c.horizon_days, call_scores.c.stock_return_pct,
                  call_scores.c.imoex_return_pct, call_scores.c.verdict,
                  call_scores.c.scored_at).select_from(j)
    if asked_by is not None:
        stmt = stmt.where(calls.c.asked_by == asked_by)
    rows = (await session.execute(stmt)).fetchall()
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


@dataclass(frozen=True)
class SimilarCall:
    ticker: str
    stance: str
    created_at: datetime
    summary: str
    score_20d: ScoredCall | None


@dataclass(frozen=True)
class HistoryItem:
    created_at: datetime
    source: str
    stance: str
    confidence: float
    summary: str
    score_20d: ScoredCall | None


def _score_row_to_scored(call_row, s_horizon, s_stock, s_imoex, s_verdict) -> ScoredCall | None:
    if s_horizon is None:
        return None
    return ScoredCall(ticker=call_row.ticker, stance=call_row.stance,
                      created_at=call_row.created_at, source=call_row.source,
                      horizon_days=s_horizon, stock_return_pct=s_stock,
                      imoex_return_pct=s_imoex, verdict=s_verdict)


def _calls_with_score20():
    return calls.outerjoin(call_scores, and_(call_scores.c.call_id == calls.c.id,
                                             call_scores.c.horizon_days == 20))


async def find_similar_calls(session: AsyncSession, embedding: list[float],
                             k: int = 3, *,
                             asked_by: int | None = None) -> list[SimilarCall]:
    """asked_by: память = СВОЙ прошлый опыт (council-summary может содержать позицию)."""
    stmt = select(calls, call_scores.c.horizon_days, call_scores.c.stock_return_pct,
                  call_scores.c.imoex_return_pct, call_scores.c.verdict) \
        .select_from(_calls_with_score20()) \
        .where(calls.c.embedding.isnot(None))
    if asked_by is not None:
        stmt = stmt.where(calls.c.asked_by == asked_by)
    rows = (await session.execute(
        stmt.order_by(calls.c.embedding.cosine_distance(embedding))
        .limit(k))).fetchall()
    out = []
    for r in rows:
        score = _score_row_to_scored(r, r.horizon_days, r.stock_return_pct,
                                     r.imoex_return_pct, r.verdict)
        out.append(SimilarCall(ticker=r.ticker, stance=r.stance,
                               created_at=r.created_at, summary=r.summary,
                               score_20d=score))
    return out


async def council_ran_recently(session: AsyncSession, ticker: str,
                               hours: int = 24) -> bool:
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    row = (await session.execute(
        select(calls.c.id).where(calls.c.ticker == ticker,
                                 calls.c.source == "council",
                                 calls.c.created_at >= since).limit(1))).first()
    return row is not None


async def get_ticker_history(session: AsyncSession, ticker: str,
                             limit: int = 5, *,
                             asked_by: int | None = None) -> list[HistoryItem]:
    stmt = select(calls, call_scores.c.horizon_days, call_scores.c.stock_return_pct,
                  call_scores.c.imoex_return_pct, call_scores.c.verdict) \
        .select_from(_calls_with_score20()) \
        .where(calls.c.ticker == ticker)
    if asked_by is not None:
        stmt = stmt.where(calls.c.asked_by == asked_by)
    rows = (await session.execute(
        stmt.order_by(calls.c.created_at.desc())
        .limit(limit))).fetchall()
    return [HistoryItem(created_at=r.created_at, source=r.source, stance=r.stance,
                        confidence=r.confidence, summary=r.summary,
                        score_20d=_score_row_to_scored(r, r.horizon_days,
                                                       r.stock_return_pct,
                                                       r.imoex_return_pct, r.verdict))
            for r in rows]


async def get_retro_seeded_keys(session: AsyncSession, *,
                                asked_by: int | None = None) -> set[tuple[str, date]]:
    """(ticker, дата as-of) уже посеянных retro-вызовов — для идемпотентного /seed_retro.

    asked_by: идемпотентность per-user — иначе второй юзер с тем же тикером не сеется."""
    stmt = select(calls.c.ticker, cast(calls.c.created_at, Date)) \
        .where(calls.c.source == "retro")
    if asked_by is not None:
        stmt = stmt.where(calls.c.asked_by == asked_by)
    rows = (await session.execute(stmt)).fetchall()
    return {(r[0], r[1]) for r in rows}
