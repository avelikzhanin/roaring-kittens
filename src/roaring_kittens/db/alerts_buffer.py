from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import alert_buffer


async def push_alert(session: AsyncSession, chat_id: int, payload: str) -> None:
    await session.execute(alert_buffer.insert().values(chat_id=chat_id, payload=payload))


async def drain_alerts(session: AsyncSession, chat_id: int) -> list[str]:
    rows = (await session.execute(
        select(alert_buffer.c.id, alert_buffer.c.payload)
        .where(alert_buffer.c.chat_id == chat_id)
        .order_by(alert_buffer.c.created_at))).fetchall()
    if rows:
        await session.execute(
            delete(alert_buffer).where(alert_buffer.c.id.in_([r[0] for r in rows])))
    return [r[1] for r in rows]
