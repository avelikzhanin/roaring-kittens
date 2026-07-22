import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.calls import (
    council_ran_recently, find_similar_calls, get_ticker_history, save_call, save_score,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

NOW = datetime.now(tz=timezone.utc)


def _vec(direction: int) -> list[float]:
    v = [0.0] * 1536
    v[direction] = 1.0
    return v


async def _save(session, *, ticker="SBER", stance="bullish", embedding=None,
                source="ask", created_at=None, asked_by=1):
    return await save_call(
        session, asked_by=asked_by, ticker=ticker, figi="F", source=source,
        question=None, stance=stance, confidence=0.6, summary=f"{ticker} разбор",
        price_at_call=Decimal("100"), news_urls=[], created_at=created_at,
        embedding=embedding)


async def test_find_similar_returns_nearest_with_score(db_session_factory):
    async with db_session_factory() as session:
        near = await _save(session, ticker="GAZP", embedding=_vec(0))
        await _save(session, ticker="LKOH", embedding=_vec(1))
        await _save(session, ticker="NONE", embedding=None)  # без эмбеддинга — вне поиска
        await save_score(session, near, 20, Decimal("5.0"), Decimal("1.0"), "hit")
        await session.commit()
    async with db_session_factory() as session:
        similar = await find_similar_calls(session, _vec(0), k=2)
        assert similar[0].ticker == "GAZP"
        assert similar[0].score_20d is not None and similar[0].score_20d.verdict == "hit"
        assert similar[1].ticker == "LKOH" and similar[1].score_20d is None


async def test_council_ran_recently_and_history(db_session_factory):
    async with db_session_factory() as session:
        await _save(session, ticker="SBER", source="council")
        await _save(session, ticker="SBER", source="ask",
                    created_at=NOW - timedelta(days=2))
        await session.commit()
    async with db_session_factory() as session:
        assert await council_ran_recently(session, "SBER", hours=24) is True
        assert await council_ran_recently(session, "GAZP", hours=24) is False
        history = await get_ticker_history(session, "SBER", limit=5)
        assert len(history) == 2 and history[0].source == "council"  # свежие первыми


async def test_memory_and_history_scoped_by_asked_by(db_session_factory):
    """Council-summary видел позицию инициатора — в чужую память/историю нельзя."""
    async with db_session_factory() as session:
        await _save(session, ticker="GAZP", embedding=_vec(0), asked_by=42,
                    source="council")
        await _save(session, ticker="LKOH", embedding=_vec(0), asked_by=777)
        await session.commit()
    async with db_session_factory() as session:
        mine = await find_similar_calls(session, _vec(0), k=5, asked_by=42)
        assert [s.ticker for s in mine] == ["GAZP"]
        history = await get_ticker_history(session, "LKOH", limit=5, asked_by=42)
        assert history == []  # чужой разбор не виден
