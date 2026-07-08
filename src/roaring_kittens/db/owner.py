"""Владелец бота — первый пользователь, нажавший /start (или ADMIN_TELEGRAM_ID из env).

Бот привязан к одному счёту Tinkoff, поэтому личные команды (/portfolio, дайджест)
доступны только владельцу; /ask открыт всем.
"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from roaring_kittens.db.tables import bot_state

OWNER_KEY = "owner_telegram_id"


async def get_owner_id(session: AsyncSession) -> int | None:
    value = (await session.execute(
        select(bot_state.c.value).where(bot_state.c.key == OWNER_KEY)
    )).scalar_one_or_none()
    return int(value) if value else None


async def claim_owner(session: AsyncSession, telegram_id: int) -> bool:
    """Атомарно занимает слот владельца. True — если владелец только что назначен."""
    stmt = insert(bot_state).values(key=OWNER_KEY, value=str(telegram_id)) \
        .on_conflict_do_nothing(index_elements=["key"])
    result = await session.execute(stmt)
    return bool(result.rowcount)


async def fetch_owner_id(session_factory: async_sessionmaker[AsyncSession]) -> int | None:
    async with session_factory() as session:
        return await get_owner_id(session)
