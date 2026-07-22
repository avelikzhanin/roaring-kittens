from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import alert_buffer


async def push_alert(session: AsyncSession, chat_id: int, payload: str) -> None:
    await session.execute(alert_buffer.insert().values(chat_id=chat_id, payload=payload))


async def fetch_alerts(session: AsyncSession, chat_id: int) -> list[tuple[int, str]]:
    """(id, payload) в устойчивом порядке. Удаление — ОТДЕЛЬНО, после успешной отправки."""
    rows = (await session.execute(
        select(alert_buffer.c.id, alert_buffer.c.payload)
        .where(alert_buffer.c.chat_id == chat_id)
        .order_by(alert_buffer.c.created_at, alert_buffer.c.id))).fetchall()
    return [(r[0], r[1]) for r in rows]


async def delete_alerts(session: AsyncSession, ids: list[int]) -> None:
    if not ids:
        return
    await session.execute(delete(alert_buffer).where(alert_buffer.c.id.in_(ids)))


async def list_buffered_chats(session: AsyncSession) -> list[int]:
    """Чаты с непустым буфером — дренаж покрывает всех (и только что revoked)."""
    rows = (await session.execute(
        select(alert_buffer.c.chat_id).distinct())).fetchall()
    return [r[0] for r in rows]
