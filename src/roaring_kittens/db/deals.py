from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import deals


@dataclass(frozen=True)
class DealRecord:
    id: UUIDType
    deal_no: int
    user_id: int
    ticker: str
    figi: str
    status: str
    source: str
    council_run_id: UUIDType | None
    proposed_at: datetime
    entry_suggested: Decimal | None
    qty_suggested: Decimal | None
    entry_actual: Decimal | None
    qty_actual: Decimal | None
    opened_at: datetime | None
    target_price: Decimal
    exit_price: Decimal
    exit_note: str
    signal_muted_until: datetime | None
    closed_at: datetime | None
    close_reason: str | None
    exit_actual: Decimal | None
    result_pct: Decimal | None


def _row(r) -> DealRecord:
    return DealRecord(**{f: getattr(r, f) for f in DealRecord.__dataclass_fields__})


async def create_proposal(session: AsyncSession, *, user_id: int, ticker: str,
                          figi: str, source: str,
                          council_run_id: UUIDType | None,
                          entry_suggested: Decimal | None,
                          qty_suggested: Decimal | None,
                          target_price: Decimal, exit_price: Decimal,
                          exit_note: str,
                          status: str = "proposed") -> DealRecord:
    result = await session.execute(deals.insert().values(
        user_id=user_id, ticker=ticker, figi=figi, source=source, status=status,
        council_run_id=council_run_id, entry_suggested=entry_suggested,
        qty_suggested=qty_suggested, target_price=target_price,
        exit_price=exit_price, exit_note=exit_note).returning(deals))
    return _row(result.first())


async def get_deal(session: AsyncSession, deal_id: UUIDType) -> DealRecord | None:
    row = (await session.execute(
        select(deals).where(deals.c.id == deal_id))).first()
    return _row(row) if row else None


async def list_deals(session: AsyncSession, user_id: int, *,
                     statuses: tuple[str, ...]) -> list[DealRecord]:
    rows = (await session.execute(
        select(deals).where(deals.c.user_id == user_id,
                            deals.c.status.in_(statuses))
        .order_by(deals.c.proposed_at))).fetchall()
    return [_row(r) for r in rows]


async def list_all_active_deals(session: AsyncSession) -> list[DealRecord]:
    """Все active-сделки всех юзеров одним запросом (для watch_deal_levels)."""
    rows = (await session.execute(
        select(deals).where(deals.c.status == "active")
        .order_by(deals.c.proposed_at))).fetchall()
    return [_row(r) for r in rows]


async def has_recent_proposal(session: AsyncSession, user_id: int, ticker: str,
                              *, days: int = 7) -> bool:
    """Любая сделка по тикеру за окно глушит новую идею — В ТОМ ЧИСЛЕ declined:
    «Пропущу» = «не предлагай неделю» (решение 1). Исключение — только expired,
    которое юзер вообще не видел/не трогал."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    row = (await session.execute(
        select(deals.c.id).where(
            deals.c.user_id == user_id, deals.c.ticker == ticker,
            deals.c.status != "expired",
            deals.c.proposed_at >= since).limit(1))).first()
    return row is not None


async def has_live_deal(session: AsyncSession, user_id: int, ticker: str) -> bool:
    """Есть ли уже accepted/active сделка по тикеру — гейт двойного покрытия."""
    row = (await session.execute(
        select(deals.c.id).where(
            deals.c.user_id == user_id, deals.c.ticker == ticker,
            deals.c.status.in_(("accepted", "active"))).limit(1))).first()
    return row is not None


async def accept_deal(session: AsyncSession, deal_id: UUIDType) -> bool:
    """True — принята; False — уже не proposed (двойной тап/старая кнопка)."""
    result = await session.execute(
        update(deals).where(deals.c.id == deal_id,
                            deals.c.status == "proposed")
        .values(status="accepted"))
    return bool(result.rowcount)


async def decline_deal(session: AsyncSession, deal_id: UUIDType) -> bool:
    """True — отклонена; False — уже не proposed (гард от тапа по active)."""
    result = await session.execute(
        update(deals).where(deals.c.id == deal_id,
                            deals.c.status == "proposed")
        .values(status="declined"))
    return bool(result.rowcount)


async def expire_deal(session: AsyncSession, deal_id: UUIDType) -> None:
    """Снять живое предложение/принятие (дубль покрытия, TTL accepted)."""
    await session.execute(
        update(deals).where(deals.c.id == deal_id,
                            deals.c.status.in_(("proposed", "accepted")))
        .values(status="expired"))


async def activate_deal(session: AsyncSession, deal_id: UUIDType, *,
                        entry_actual: Decimal, qty_actual: Decimal) -> None:
    await session.execute(update(deals).where(deals.c.id == deal_id)
                          .values(status="active", entry_actual=entry_actual,
                                  qty_actual=qty_actual,
                                  opened_at=datetime.now(tz=timezone.utc)))


async def mute_deal(session: AsyncSession, deal_id: UUIDType, *,
                    until: datetime) -> None:
    await session.execute(update(deals).where(deals.c.id == deal_id)
                          .values(signal_muted_until=until))


async def close_deal(session: AsyncSession, deal_id: UUIDType, *,
                     exit_actual: Decimal | None, close_reason: str,
                     result_pct: Decimal | None) -> None:
    await session.execute(update(deals).where(deals.c.id == deal_id)
                          .values(status="closed", exit_actual=exit_actual,
                                  close_reason=close_reason, result_pct=result_pct,
                                  closed_at=datetime.now(tz=timezone.utc)))


async def expire_if_stale(session: AsyncSession, deal_id: UUIDType, *,
                          ttl_hours: int = 48) -> bool:
    """True — предложение протухло (переведено в expired). Только для proposed."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=ttl_hours)
    result = await session.execute(
        update(deals).where(deals.c.id == deal_id,
                            deals.c.status == "proposed",
                            deals.c.proposed_at < cutoff)
        .values(status="expired"))
    return bool(result.rowcount)
