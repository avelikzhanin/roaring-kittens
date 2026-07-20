import os

import pytest

from roaring_kittens.db.watchlist import (
    add_to_watchlist, list_watchlist, remove_from_watchlist,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_add_list_remove_idempotent(db_session_factory):
    async with db_session_factory() as session:
        assert await add_to_watchlist(session, 42, "SBER") is True
        assert await add_to_watchlist(session, 42, "SBER") is False  # уже есть
        assert await add_to_watchlist(session, 42, "GAZP") is True
        await session.commit()
    async with db_session_factory() as session:
        assert await list_watchlist(session, 42) == ["GAZP", "SBER"]  # алфавитный
        assert await list_watchlist(session, 999) == []
        assert await remove_from_watchlist(session, 42, "SBER") is True
        assert await remove_from_watchlist(session, 42, "SBER") is False
        await session.commit()
        assert await list_watchlist(session, 42) == ["GAZP"]
