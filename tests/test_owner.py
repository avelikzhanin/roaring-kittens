import os

import pytest

from roaring_kittens.db.owner import claim_owner, get_owner_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_first_claim_wins_second_is_noop(db_session_factory):
    async with db_session_factory() as session:
        assert await get_owner_id(session) is None
        assert await claim_owner(session, 111) is True
        await session.commit()

    async with db_session_factory() as session:
        assert await claim_owner(session, 222) is False  # слот уже занят
        await session.commit()
        assert await get_owner_id(session) == 111


async def test_claim_is_idempotent_for_same_user(db_session_factory):
    async with db_session_factory() as session:
        assert await claim_owner(session, 111) is True
        assert await claim_owner(session, 111) is False  # повторный /start того же юзера
        await session.commit()
        assert await get_owner_id(session) == 111
