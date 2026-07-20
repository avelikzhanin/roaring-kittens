from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import watchlists


async def add_to_watchlist(session: AsyncSession, owner_id: int, ticker: str) -> bool:
    stmt = insert(watchlists).values(owner_id=owner_id, ticker=ticker) \
        .on_conflict_do_nothing(index_elements=["owner_id", "ticker"])
    result = await session.execute(stmt)
    return bool(result.rowcount)


async def remove_from_watchlist(session: AsyncSession, owner_id: int, ticker: str) -> bool:
    result = await session.execute(
        delete(watchlists).where(watchlists.c.owner_id == owner_id,
                                 watchlists.c.ticker == ticker))
    return bool(result.rowcount)


async def list_watchlist(session: AsyncSession, owner_id: int) -> list[str]:
    rows = (await session.execute(
        select(watchlists.c.ticker).where(watchlists.c.owner_id == owner_id)
        .order_by(watchlists.c.ticker))).fetchall()
    return [r[0] for r in rows]
