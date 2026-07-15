import os
from datetime import datetime, timedelta, timezone

import pytest

from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers, save_news

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


def _item(url, headline="h", tickers=None, age_hours=1):
    return NewsItem(
        source="test", url=url, headline=headline, body="b",
        published_at=datetime.now(tz=timezone.utc) - timedelta(hours=age_hours),
        tickers=tickers or [],
    )


async def test_save_dedupes_by_url(db_session_factory):
    items = [_item("https://x/1", tickers=["SBER"]), _item("https://x/1", tickers=["SBER"])]
    async with db_session_factory() as session:
        inserted = await save_news(session, items)
        await session.commit()
    assert inserted == ["https://x/1"]  # возвращаются url'ы реально вставленных
    async with db_session_factory() as session:
        again = await save_news(session, [_item("https://x/1")])
        await session.commit()
    assert again == []


async def test_query_by_ticker_and_window(db_session_factory):
    async with db_session_factory() as session:
        await save_news(session, [
            _item("https://x/sber", headline="про сбер", tickers=["SBER"], age_hours=2),
            _item("https://x/gazp", headline="про газпром", tickers=["GAZP"], age_hours=2),
            _item("https://x/old", headline="старое про сбер", tickers=["SBER"], age_hours=100),
        ])
        await session.commit()
    async with db_session_factory() as session:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        rows = await get_news_for_tickers(session, ["SBER"], since=since)
    assert [r.headline for r in rows] == ["про сбер"]
