import os

import pytest

from roaring_kittens.db.insights import (
    bump_times_applied, list_active_insights, save_insight, top_insights_by_similarity,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


def _vec(direction: int) -> list[float]:
    v = [0.0] * 1536
    v[direction] = 1.0
    return v


async def test_similarity_orders_and_filters(db_session_factory):
    async with db_session_factory() as session:
        near = await save_insight(session, summary="банки под дивы работают",
                                  scope="pattern", scope_value="banks_divs",
                                  confidence=0.8, embedding=_vec(0))
        far = await save_insight(session, summary="металлурги слабы",
                                 scope="sector", scope_value="metals",
                                 confidence=0.9, embedding=_vec(1))
        weak = await save_insight(session, summary="слабый урок",
                                  scope="general", scope_value=None,
                                  confidence=0.2, embedding=_vec(0))
        await session.commit()
    async with db_session_factory() as session:
        top = await top_insights_by_similarity(session, _vec(0), k=2, min_confidence=0.5)
        assert [i.id for i in top] == [near.id, far.id]  # weak отфильтрован по confidence
        await bump_times_applied(session, [near.id])
        await session.commit()
        active = await list_active_insights(session)
        bumped = next(i for i in active if i.id == near.id)
        assert bumped.times_applied == 1
