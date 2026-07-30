from uuid import UUID as UUIDType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import council_runs


async def save_council_run(session: AsyncSession, *, ticker: str, asked_by: int,
                           transcript: dict, call_id: UUIDType | None) -> UUIDType:
    result = await session.execute(
        council_runs.insert().values(ticker=ticker, asked_by=asked_by,
                                     transcript=transcript, call_id=call_id)
        .returning(council_runs.c.id))
    return result.scalar_one()


async def get_council_transcript(session: AsyncSession,
                                 run_id: UUIDType | None) -> dict | None:
    if run_id is None:
        return None
    row = (await session.execute(
        select(council_runs.c.transcript).where(council_runs.c.id == run_id))).first()
    return row[0] if row else None


async def council_run_recently(session: AsyncSession, ticker: str,
                               hours: int) -> bool:
    """Был ли ЛЮБОЙ прогон комитета по тикеру (включая вето — в calls их нет).

    Для сканера: council_ran_recently из db/calls слеп к vetoed-прогонам —
    без этого guard'а сканер жёг бы комитет по одному отклоняемому тикеру ежедневно."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    row = (await session.execute(
        select(council_runs.c.id).where(council_runs.c.ticker == ticker,
                                        council_runs.c.created_at >= since)
        .limit(1))).first()
    return row is not None


async def get_council_run(session: AsyncSession,
                          run_id: UUIDType | None) -> tuple[dict, int] | None:
    """(transcript, asked_by) — колбэкам нужен владелец прогона для гейта."""
    if run_id is None:
        return None
    row = (await session.execute(
        select(council_runs.c.transcript, council_runs.c.asked_by)
        .where(council_runs.c.id == run_id))).first()
    return (row[0], row[1]) if row else None
