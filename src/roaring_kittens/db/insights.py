from dataclasses import dataclass
from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import insights


@dataclass(frozen=True)
class InsightRecord:
    id: UUIDType
    created_at: datetime
    summary: str
    scope: str
    scope_value: str | None
    confidence: float
    times_applied: int


def _row(r) -> InsightRecord:
    return InsightRecord(id=r.id, created_at=r.created_at, summary=r.summary,
                         scope=r.scope, scope_value=r.scope_value,
                         confidence=r.confidence, times_applied=r.times_applied)


async def save_insight(session: AsyncSession, *, summary: str, scope: str,
                       scope_value: str | None, confidence: float,
                       embedding: list[float] | None) -> InsightRecord:
    result = await session.execute(
        insights.insert().values(summary=summary, scope=scope, scope_value=scope_value,
                                 confidence=confidence, embedding=embedding)
        .returning(insights))
    return _row(result.first())


async def top_insights_by_similarity(session: AsyncSession, embedding: list[float],
                                     k: int = 3,
                                     min_confidence: float = 0.5) -> list[InsightRecord]:
    rows = (await session.execute(
        select(insights)
        .where(insights.c.archived_at.is_(None),
               insights.c.confidence >= min_confidence,
               insights.c.embedding.isnot(None))
        .order_by(insights.c.embedding.cosine_distance(embedding))
        .limit(k))).fetchall()
    return [_row(r) for r in rows]


async def bump_times_applied(session: AsyncSession, ids: list[UUIDType]) -> None:
    if not ids:
        return
    await session.execute(
        update(insights).where(insights.c.id.in_(ids))
        .values(times_applied=insights.c.times_applied + 1))


async def list_active_insights(session: AsyncSession) -> list[InsightRecord]:
    rows = (await session.execute(
        select(insights).where(insights.c.archived_at.is_(None))
        .order_by(insights.c.created_at.desc()))).fetchall()
    return [_row(r) for r in rows]
