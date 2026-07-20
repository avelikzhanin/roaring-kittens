import os

import pytest

from roaring_kittens.db.alerts_buffer import drain_alerts, push_alert

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_push_and_drain_clears(db_session_factory):
    async with db_session_factory() as session:
        await push_alert(session, 42, "первый")
        await push_alert(session, 42, "второй")
        await push_alert(session, 777, "чужой")
        await session.commit()
    async with db_session_factory() as session:
        drained = await drain_alerts(session, 42)
        await session.commit()
        assert drained == ["первый", "второй"]  # по created_at
    async with db_session_factory() as session:
        assert await drain_alerts(session, 42) == []          # опустошён
        assert await drain_alerts(session, 777) == ["чужой"]  # чужие не тронуты
