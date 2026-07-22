import os

import pytest

from roaring_kittens.db.alerts_buffer import delete_alerts, fetch_alerts, push_alert

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_fetch_is_ordered_and_delete_is_explicit(db_session_factory):
    # Коммит на каждый push: now() в Postgres — timestamp ТРАНЗАКЦИИ, в одной
    # транзакции created_at совпадут и порядок станет лотереей случайных UUID.
    # Прод буферит так же — send_alert коммитит каждый алерт отдельно.
    async with db_session_factory() as session:
        await push_alert(session, 42, "первый")
        await session.commit()
    async with db_session_factory() as session:
        await push_alert(session, 42, "второй")
        await push_alert(session, 777, "чужой")
        await session.commit()
    async with db_session_factory() as session:
        rows = await fetch_alerts(session, 42)
        assert [p for _, p in rows] == ["первый", "второй"]  # created_at, id
        # fetch БЕЗ удаления — сбой отправки не теряет алерты
        again = await fetch_alerts(session, 42)
        assert len(again) == 2
        await delete_alerts(session, [rid for rid, _ in rows])
        await session.commit()
    async with db_session_factory() as session:
        assert await fetch_alerts(session, 42) == []
        assert [p for _, p in await fetch_alerts(session, 777)] == ["чужой"]
