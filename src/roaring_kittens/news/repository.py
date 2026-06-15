from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import news_events
from roaring_kittens.news.models import NewsItem


async def save_news(session: AsyncSession, items: list[NewsItem]) -> int:
    """Вставка с дедупом по url. Возвращает число реально вставленных.

    Дедуп идёт в два слоя: в Python (на случай дублей внутри одной пачки, где
    ON CONFLICT внутри одного INSERT ненадёжен) и в БД (против уже сохранённых)."""
    if not items:
        return 0
    seen: set[str] = set()
    rows = []
    for i in items:
        if i.url in seen:
            continue
        seen.add(i.url)
        rows.append(dict(published_at=i.published_at, tickers=i.tickers, source=i.source,
                         headline=i.headline, body=i.body, url=i.url))
    stmt = insert(news_events).values(rows).on_conflict_do_nothing(index_elements=["url"])
    result = await session.execute(stmt)
    return result.rowcount or 0


async def get_news_for_tickers(session: AsyncSession, tickers: list[str],
                               since: datetime, limit: int = 50) -> list[NewsItem]:
    stmt = (
        select(news_events)
        .where(news_events.c.published_at >= since)
        .where(news_events.c.tickers.overlap(tickers))
        .order_by(news_events.c.published_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).fetchall()
    return [
        NewsItem(source=r.source, url=r.url, headline=r.headline, body=r.body,
                 published_at=r.published_at, tickers=list(r.tickers))
        for r in rows
    ]
