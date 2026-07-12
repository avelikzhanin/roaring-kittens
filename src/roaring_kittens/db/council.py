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
