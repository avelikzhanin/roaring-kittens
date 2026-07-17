from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import theses

TECH_CLOSE_REASONS = ("superseded", "удалён владельцем")


@dataclass(frozen=True)
class ThesisRecord:
    id: UUIDType
    ticker: str
    figi: str
    opened_at: datetime
    closed_at: datetime | None
    status: str
    thesis: str
    invalidation: str
    source: str
    confidence: float | None
    entry_price: Decimal | None
    realized_return_pct: Decimal | None
    close_reason: str | None
    backed_by_position: bool = False  # False = «идея» без реальной позиции
    last_weakened_at: datetime | None = None  # для кулдауна «ослаблен»-уведомлений


def _row(r) -> ThesisRecord:
    return ThesisRecord(id=r.id, ticker=r.ticker, figi=r.figi, opened_at=r.opened_at,
                        closed_at=r.closed_at, status=r.status, thesis=r.thesis,
                        invalidation=r.invalidation, source=r.source,
                        confidence=r.confidence, entry_price=r.entry_price,
                        realized_return_pct=r.realized_return_pct,
                        close_reason=r.close_reason,
                        backed_by_position=r.backed_by_position,
                        last_weakened_at=r.last_weakened_at)


async def save_thesis(session: AsyncSession, *, ticker: str, figi: str, thesis: str,
                      invalidation: str, source: str, confidence: float | None,
                      entry_price: Decimal | None,
                      backed_by_position: bool = False) -> ThesisRecord:
    """Один активный тезис на тикер: прежний закрывается как superseded."""
    await session.execute(
        update(theses)
        .where(theses.c.ticker == ticker, theses.c.status == "active")
        .values(status="closed", closed_at=datetime.now(tz=timezone.utc),
                close_reason="superseded"))
    result = await session.execute(
        theses.insert().values(ticker=ticker, figi=figi, thesis=thesis,
                               invalidation=invalidation, source=source,
                               confidence=confidence, entry_price=entry_price,
                               backed_by_position=backed_by_position)
        .returning(theses))
    return _row(result.first())


async def mark_thesis_weakened(session: AsyncSession, thesis_id: UUIDType) -> None:
    """Запоминаем момент «ослаблен»-уведомления — для суточного кулдауна."""
    await session.execute(
        update(theses).where(theses.c.id == thesis_id)
        .values(last_weakened_at=datetime.now(tz=timezone.utc)))


async def set_thesis_backed(session: AsyncSession, thesis_id: UUIDType) -> None:
    """Идея превратилась в реальную позицию — тезис теперь подкреплён."""
    await session.execute(
        update(theses).where(theses.c.id == thesis_id)
        .values(backed_by_position=True))


async def get_active_thesis(session: AsyncSession, ticker: str) -> ThesisRecord | None:
    row = (await session.execute(
        select(theses).where(theses.c.ticker == ticker,
                             theses.c.status == "active").limit(1))).first()
    return _row(row) if row else None


async def get_active_theses(session: AsyncSession) -> list[ThesisRecord]:
    rows = (await session.execute(
        select(theses).where(theses.c.status == "active")
        .order_by(theses.c.opened_at))).fetchall()
    return [_row(r) for r in rows]


async def close_thesis(session: AsyncSession, thesis_id: UUIDType, *, status: str,
                       realized_return_pct: Decimal | None,
                       close_reason: str) -> None:
    await session.execute(
        update(theses).where(theses.c.id == thesis_id)
        .values(status=status, closed_at=datetime.now(tz=timezone.utc),
                realized_return_pct=realized_return_pct, close_reason=close_reason))


async def get_recently_closed(session: AsyncSession, days: int = 7,
                              real_outcomes_only: bool = True) -> list[ThesisRecord]:
    """real_outcomes_only: superseded/удалённые — технический шум, не исход сделки."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = select(theses).where(theses.c.status != "active",
                                theses.c.closed_at >= since)
    if real_outcomes_only:
        stmt = stmt.where(theses.c.close_reason.notin_(TECH_CLOSE_REASONS))
    rows = (await session.execute(stmt)).fetchall()
    return [_row(r) for r in rows]


async def get_recently_deleted_tickers(session: AsyncSession,
                                       days: int = 30) -> set[str]:
    """Тикеры, чей авто-тезис владелец удалил — не регенерировать месяц."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = (await session.execute(
        select(theses.c.ticker).where(theses.c.close_reason == "удалён владельцем",
                                      theses.c.closed_at >= since))).fetchall()
    return {r[0] for r in rows}
