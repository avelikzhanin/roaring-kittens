import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from roaring_kittens.db.tables import usage_log
from roaring_kittens.db.users import (
    create_invite, get_active_user, get_user, list_active_users, month_spend,
    redeem_invite, set_user_budget, set_user_status, set_user_token, upsert_user,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

NOW = datetime.now(tz=timezone.utc)


async def test_user_lifecycle(db_session_factory):
    async with db_session_factory() as session:
        u = await upsert_user(session, 111, username="vasya")
        assert u.role == "user" and u.status == "active" and u.has_token is False
        await upsert_user(session, 111, username="vasya2")  # идемпотентно, апдейт username
        await set_user_token(session, 111, b"encrypted-token")
        await upsert_user(session, 500, username="admin", role="admin")
        await session.commit()
    async with db_session_factory() as session:
        u = await get_user(session, 111)
        assert u.username == "vasya2" and u.has_token is True
        assert await get_user(session, 999) is None
        active = await list_active_users(session)
        assert {x.telegram_id for x in active} == {111, 500}
        await set_user_status(session, 111, "revoked")
        await set_user_budget(session, 500, Decimal("40"))
        await session.commit()
    async with db_session_factory() as session:
        assert {x.telegram_id for x in await list_active_users(session)} == {500}
        assert (await get_user(session, 500)).monthly_budget_usd == Decimal("40")
        assert await get_active_user(session, 111) is None      # revoked
        assert (await get_active_user(session, 500)).role == "admin"


async def test_revoked_user_reactivates_on_reupsert(db_session_factory):
    """/admin revoke -> новый инвайт -> redeem: юзер снова active, username не затирается."""
    async with db_session_factory() as session:
        await upsert_user(session, 111, username="vasya")
        await set_user_status(session, 111, "revoked")
        await session.commit()
    async with db_session_factory() as session:
        u = await upsert_user(session, 111, username=None)  # redeem-путь без username
        assert u.status == "active"            # реактивирован
        assert u.username == "vasya"           # None не затёр сохранённое имя
        await session.commit()


async def test_invites(db_session_factory):
    async with db_session_factory() as session:
        await create_invite(session, "INV-ABC123", created_by=500, ttl_days=7)
        await create_invite(session, "INV-OLD000", created_by=500, ttl_days=7)
        await session.execute(text(  # состариваем второй
            "UPDATE invites SET expires_at = now() - interval '1 day' "
            "WHERE code = 'INV-OLD000'"))
        await session.commit()
    async with db_session_factory() as session:
        assert await redeem_invite(session, "INV-OLD000", 111) is False  # просрочен
        assert await redeem_invite(session, "INV-NOPE00", 111) is False  # нет такого
        assert await redeem_invite(session, "INV-ABC123", 111) is True
        assert await redeem_invite(session, "INV-ABC123", 222) is False  # уже погашен
        await session.commit()


async def test_month_spend_counts_current_month_for_user(db_session_factory):
    async with db_session_factory() as session:
        await session.execute(usage_log.insert().values(
            operation="x", model="m", input_tokens=1, output_tokens=1,
            cost_usd=Decimal("0.5"), user_id=111))
        await session.execute(usage_log.insert().values(
            operation="x", model="m", input_tokens=1, output_tokens=1,
            cost_usd=Decimal("0.3"), user_id=111,
            timestamp=NOW - timedelta(days=45)))          # прошлый месяц — мимо
        await session.execute(usage_log.insert().values(
            operation="x", model="m", input_tokens=1, output_tokens=1,
            cost_usd=Decimal("9.9"), user_id=222))        # чужой — мимо
        await session.commit()
    async with db_session_factory() as session:
        assert await month_spend(session, 111) == Decimal("0.5")
        assert await month_spend(session, 999) == Decimal("0")
