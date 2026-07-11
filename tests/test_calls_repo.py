import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.calls import (
    count_calls_by_source, count_unscored, get_last_call, get_scored_calls,
    get_unscored_calls, save_call, save_score,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

NOW = datetime.now(tz=timezone.utc)


async def _save(session, *, ticker="SBER", created_at=None, stance="bullish",
                price=Decimal("280"), source="ask"):
    return await save_call(
        session, asked_by=111, ticker=ticker, figi="BBG004730N88", source=source,
        question=None, stance=stance, confidence=0.7, summary="s",
        price_at_call=price, news_urls=["https://x/1"], created_at=created_at)


async def test_save_and_get_last_call_within_window(db_session_factory):
    async with db_session_factory() as session:
        await _save(session, created_at=NOW - timedelta(days=2))
        await _save(session, created_at=NOW - timedelta(days=30))  # вне окна 7д
        await session.commit()
    async with db_session_factory() as session:
        last = await get_last_call(session, "SBER", within_days=7)
        assert last is not None and last.stance == "bullish"
        assert (NOW - last.created_at).days == 2
        assert await get_last_call(session, "GAZP", within_days=7) is None


async def test_unscored_respects_horizon_price_and_existing_scores(db_session_factory):
    async with db_session_factory() as session:
        old = await _save(session, created_at=NOW - timedelta(days=10))
        fresh = await _save(session, created_at=NOW - timedelta(days=1))
        no_price = await _save(session, created_at=NOW - timedelta(days=10), price=None)
        await session.commit()
    async with db_session_factory() as session:
        ids = {c.id for c in await get_unscored_calls(session, horizon_days=5, now=NOW)}
        assert old in ids                      # старый с ценой — дозрел
        assert fresh not in ids                # моложе горизонта
        assert no_price not in ids             # NULL price не скорится
        await save_score(session, old, 5, Decimal("2.0"), Decimal("1.0"), "hit")
        await save_score(session, old, 5, Decimal("2.0"), Decimal("1.0"), "hit")  # идемпотентно
        await session.commit()
    async with db_session_factory() as session:
        assert old not in {c.id for c in await get_unscored_calls(session, 5, NOW)}
        scored = await get_scored_calls(session)
        assert len(scored) == 1 and scored[0].verdict == "hit"
        assert await count_calls_by_source(session, "retro") == 0
        # без единой оценки остался только fresh; no_price (NULL) не считается
        assert await count_unscored(session) == 1
