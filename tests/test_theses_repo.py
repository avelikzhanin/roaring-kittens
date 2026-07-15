import os
from decimal import Decimal

import pytest

from roaring_kittens.db.theses import (
    close_thesis, get_active_theses, get_active_thesis, get_recently_closed,
    get_recently_deleted_tickers, save_thesis, set_thesis_backed,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_save_supersedes_previous_active(db_session_factory):
    async with db_session_factory() as session:
        first = await save_thesis(session, ticker="SBER", figi="F", thesis="старый",
                                  invalidation="i", source="auto", confidence=0.5,
                                  entry_price=Decimal("280"))
        second = await save_thesis(session, ticker="SBER", figi="F", thesis="новый",
                                   invalidation="i2", source="council", confidence=0.7,
                                   entry_price=Decimal("290"))
        await session.commit()
    async with db_session_factory() as session:
        active = await get_active_thesis(session, "SBER")
        assert active is not None and active.id == second.id and active.thesis == "новый"
        all_active = await get_active_theses(session)
        assert [t.id for t in all_active] == [second.id]  # старый закрыт как superseded


async def test_close_thesis_and_recently_closed_filters_technical(db_session_factory):
    async with db_session_factory() as session:
        t = await save_thesis(session, ticker="GAZP", figi="F2", thesis="t",
                              invalidation="i", source="auto", confidence=0.6,
                              entry_price=None, backed_by_position=True)
        d = await save_thesis(session, ticker="PLZL", figi="F3", thesis="t2",
                              invalidation="i2", source="auto", confidence=0.5,
                              entry_price=None)
        await session.commit()
    async with db_session_factory() as session:
        await close_thesis(session, t.id, status="closed",
                           realized_return_pct=Decimal("4.2"),
                           close_reason="позиция закрыта")
        await close_thesis(session, d.id, status="closed",
                           realized_return_pct=None,
                           close_reason="удалён владельцем")
        await session.commit()
        assert await get_active_thesis(session, "GAZP") is None
        # рефлексия видит только реальные исходы — superseded/удалённые отфильтрованы
        recent = await get_recently_closed(session, days=7)
        assert [r.ticker for r in recent] == ["GAZP"]
        assert recent[0].realized_return_pct == Decimal("4.2")
        assert recent[0].backed_by_position is True
        everything = await get_recently_closed(session, days=7, real_outcomes_only=False)
        assert len(everything) == 2
        # удалённые владельцем тикеры подавляются от повторной авто-генерации
        assert await get_recently_deleted_tickers(session, days=30) == {"PLZL"}


async def test_set_thesis_backed(db_session_factory):
    async with db_session_factory() as session:
        t = await save_thesis(session, ticker="LKOH", figi="F4", thesis="идея",
                              invalidation="i", source="council", confidence=0.7,
                              entry_price=None)  # идея: backed=False по умолчанию
        await session.commit()
    async with db_session_factory() as session:
        await set_thesis_backed(session, t.id)
        await session.commit()
        active = await get_active_thesis(session, "LKOH")
        assert active.backed_by_position is True
