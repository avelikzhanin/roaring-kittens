import os
from decimal import Decimal

import pytest

from roaring_kittens.db.theses import (
    close_thesis, get_active_theses, get_active_thesis, get_recently_closed,
    get_recently_deleted_tickers, mark_thesis_weakened, save_thesis, set_thesis_backed,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_save_supersedes_previous_active(db_session_factory):
    async with db_session_factory() as session:
        first = await save_thesis(session, ticker="SBER", figi="F", thesis="старый",
                                  invalidation="i", source="auto", confidence=0.5,
                                  entry_price=Decimal("280"), owner_id=42)
        second = await save_thesis(session, ticker="SBER", figi="F", thesis="новый",
                                   invalidation="i2", source="council", confidence=0.7,
                                   entry_price=Decimal("290"), owner_id=42)
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
                              entry_price=None, backed_by_position=True, owner_id=42)
        d = await save_thesis(session, ticker="PLZL", figi="F3", thesis="t2",
                              invalidation="i2", source="auto", confidence=0.5,
                              entry_price=None, owner_id=42)
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


async def test_theses_are_scoped_per_owner(db_session_factory):
    async with db_session_factory() as session:
        await save_thesis(session, ticker="SBER", figi="F", thesis="мой",
                          invalidation="i", source="auto", confidence=0.5,
                          entry_price=None, owner_id=42)
        await save_thesis(session, ticker="SBER", figi="F", thesis="чужой",
                          invalidation="i", source="auto", confidence=0.5,
                          entry_price=None, owner_id=777)
        await session.commit()
    async with db_session_factory() as session:
        mine = await get_active_thesis(session, "SBER", owner_id=42)
        theirs = await get_active_thesis(session, "SBER", owner_id=777)
        assert mine.thesis == "мой" and theirs.thesis == "чужой"  # не supersede друг друга
        assert len(await get_active_theses(session)) == 2          # None = все
        # чужой thesis_id не закрывается с owner-условием (гейт колбэков)
        await close_thesis(session, mine.id, status="closed",
                           realized_return_pct=None, close_reason="удалён владельцем",
                           owner_id=777)
        await session.commit()
        assert await get_active_thesis(session, "SBER", owner_id=42) is not None


async def test_set_thesis_backed(db_session_factory):
    async with db_session_factory() as session:
        t = await save_thesis(session, ticker="LKOH", figi="F4", thesis="идея",
                              invalidation="i", source="council", confidence=0.7,
                              entry_price=None, owner_id=42)  # идея: backed=False по умолчанию
        await session.commit()
    async with db_session_factory() as session:
        await set_thesis_backed(session, t.id)
        await session.commit()
        active = await get_active_thesis(session, "LKOH")
        assert active.backed_by_position is True


async def test_mark_thesis_weakened_sets_cooldown_timestamp(db_session_factory):
    async with db_session_factory() as session:
        t = await save_thesis(session, ticker="NVTK", figi="F5", thesis="t",
                              invalidation="i", source="auto", confidence=0.5,
                              entry_price=None, owner_id=42)
        await session.commit()
        assert t.last_weakened_at is None
    async with db_session_factory() as session:
        await mark_thesis_weakened(session, t.id)
        await session.commit()
        active = await get_active_thesis(session, "NVTK")
        assert active.last_weakened_at is not None
