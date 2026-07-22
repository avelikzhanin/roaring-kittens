from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import invites, usage_log, users


@dataclass(frozen=True)
class UserRecord:
    telegram_id: int
    username: str | None
    role: str
    status: str
    has_token: bool
    monthly_budget_usd: Decimal
    created_at: datetime


def _row(r) -> UserRecord:
    return UserRecord(telegram_id=r.telegram_id, username=r.username, role=r.role,
                      status=r.status, has_token=r.tinkoff_token_enc is not None,
                      monthly_budget_usd=r.monthly_budget_usd, created_at=r.created_at)


async def upsert_user(session: AsyncSession, telegram_id: int, *,
                      username: str | None = None, role: str = "user",
                      status: str = "active") -> UserRecord:
    stmt = insert(users).values(telegram_id=telegram_id, username=username,
                                role=role, status=status)
    # Повторный upsert (redeem нового инвайта) РЕАКТИВИРУЕТ revoked-юзера;
    # username=None не затирает сохранённое имя (coalesce с excluded).
    stmt = stmt.on_conflict_do_update(
        index_elements=["telegram_id"],
        set_={"username": func.coalesce(stmt.excluded.username, users.c.username),
              "status": "active"}) \
        .returning(users)
    return _row((await session.execute(stmt)).first())


async def get_user(session: AsyncSession, telegram_id: int) -> UserRecord | None:
    row = (await session.execute(
        select(users).where(users.c.telegram_id == telegram_id))).first()
    return _row(row) if row else None


async def get_active_user(session: AsyncSession, telegram_id: int) -> UserRecord | None:
    u = await get_user(session, telegram_id)
    return u if u is not None and u.status == "active" else None


async def get_user_token(session: AsyncSession, telegram_id: int) -> bytes | None:
    row = (await session.execute(
        select(users.c.tinkoff_token_enc)
        .where(users.c.telegram_id == telegram_id))).first()
    return row[0] if row else None


async def set_user_token(session: AsyncSession, telegram_id: int,
                         encrypted: bytes | None) -> None:
    await session.execute(update(users).where(users.c.telegram_id == telegram_id)
                          .values(tinkoff_token_enc=encrypted))


async def set_user_status(session: AsyncSession, telegram_id: int, status: str) -> None:
    await session.execute(update(users).where(users.c.telegram_id == telegram_id)
                          .values(status=status))


async def set_user_budget(session: AsyncSession, telegram_id: int,
                          budget: Decimal) -> None:
    await session.execute(update(users).where(users.c.telegram_id == telegram_id)
                          .values(monthly_budget_usd=budget))


async def list_active_users(session: AsyncSession) -> list[UserRecord]:
    rows = (await session.execute(
        select(users).where(users.c.status == "active")
        .order_by(users.c.created_at))).fetchall()
    return [_row(r) for r in rows]


async def create_invite(session: AsyncSession, code: str, *, created_by: int,
                        ttl_days: int = 7) -> None:
    await session.execute(invites.insert().values(
        code=code, created_by=created_by,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=ttl_days)))


async def redeem_invite(session: AsyncSession, code: str, telegram_id: int) -> bool:
    """Атомарно гасит живой код. False — нет/просрочен/уже погашен."""
    result = await session.execute(
        update(invites)
        .where(invites.c.code == code,
               invites.c.redeemed_by.is_(None),
               invites.c.expires_at > datetime.now(tz=timezone.utc))
        .values(redeemed_by=telegram_id))
    return bool(result.rowcount)


async def month_spend(session: AsyncSession, telegram_id: int) -> Decimal:
    start = datetime.now(tz=timezone.utc).replace(day=1, hour=0, minute=0,
                                                  second=0, microsecond=0)
    value = (await session.execute(
        select(func.coalesce(func.sum(usage_log.c.cost_usd), 0))
        .where(usage_log.c.user_id == telegram_id,
               usage_log.c.timestamp >= start))).scalar_one()
    return Decimal(value)
