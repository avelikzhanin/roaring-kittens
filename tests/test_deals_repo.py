import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from roaring_kittens.db.deals import (
    accept_deal, activate_deal, close_deal, create_proposal, decline_deal,
    expire_if_stale, get_deal, has_live_deal, has_recent_proposal, list_deals,
    mute_deal,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def _propose(session, user_id=42, ticker="SBER"):
    return await create_proposal(
        session, user_id=user_id, ticker=ticker, figi="F", source="council",
        council_run_id=None, entry_suggested=Decimal("262"),
        qty_suggested=Decimal("10"), target_price=Decimal("290"),
        exit_price=Decimal("245"), exit_note="отменят дивиденды")


async def test_deal_lifecycle(db_session_factory):
    async with db_session_factory() as session:
        d = await _propose(session)
        assert d.status == "proposed" and d.deal_no >= 1
        assert await has_recent_proposal(session, 42, "SBER", days=7) is True
        assert await has_recent_proposal(session, 42, "GAZP", days=7) is False
        assert await has_recent_proposal(session, 777, "SBER", days=7) is False
        assert await accept_deal(session, d.id) is True
        assert await accept_deal(session, d.id) is False   # двойной тап
        assert await has_live_deal(session, 42, "SBER") is True
        await activate_deal(session, d.id, entry_actual=Decimal("262.3"),
                            qty_actual=Decimal("10"))
        await session.commit()
    async with db_session_factory() as session:
        d2 = await get_deal(session, d.id)
        assert d2.status == "active" and d2.entry_actual == Decimal("262.3")
        active = await list_deals(session, 42, statuses=("active",))
        assert [x.id for x in active] == [d.id]
        await close_deal(session, d.id, exit_actual=Decimal("270"),
                         close_reason="продал по кнопке",
                         result_pct=Decimal("2.9"))
        await session.commit()
    async with db_session_factory() as session:
        d3 = await get_deal(session, d.id)
        assert d3.status == "closed" and d3.result_pct == Decimal("2.9")


async def test_decline_mute_and_expire(db_session_factory):
    async with db_session_factory() as session:
        a = await _propose(session, ticker="GAZP")
        b = await _propose(session, ticker="LKOH")
        assert await decline_deal(session, a.id) is True
        assert await decline_deal(session, a.id) is False  # уже не proposed
        # «Пропущу» глушит идеи по тикеру на 7 дней (решение 1)
        assert await has_recent_proposal(session, 42, "GAZP", days=7) is True
        until = datetime.now(tz=timezone.utc) + timedelta(days=3)
        await mute_deal(session, b.id, until=until)
        await session.commit()
    async with db_session_factory() as session:
        assert (await get_deal(session, a.id)).status == "declined"
        assert (await get_deal(session, b.id)).signal_muted_until is not None
        # протухание: старше 48ч -> expired, свежий -> нетронут
        stale = await expire_if_stale(session, b.id, ttl_hours=48)
        assert stale is False   # свежее предложение не протухло
        await session.execute(text(  # состариваем руками
            "UPDATE deals SET proposed_at = now() - interval '3 days' "
            "WHERE id = :i"), {"i": str(b.id)})
        assert await expire_if_stale(session, b.id, ttl_hours=48) is True
        assert (await get_deal(session, b.id)).status == "expired"
