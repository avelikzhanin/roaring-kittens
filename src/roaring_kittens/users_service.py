"""Per-user брокеры (кэш инстансов) и TTL-кэш портфелей для частых джобов."""
import time
from datetime import datetime, timedelta, timezone

import structlog

from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.db.users import get_user, get_user_token
from roaring_kittens.security.crypto import decrypt_secret

log = structlog.get_logger()

PORTFOLIO_TTL_SEC = 900  # 15 минут


async def get_user_broker(deps, telegram_id: int):
    """Брокер юзера: admin без токена -> системный; user -> свой (кэш); нет/revoked -> None.

    Статус проверяется ВСЕГДА (до кэша): кэш хранит только конструирование
    TinkoffBroker, но НЕ решение об авторизации — revoked не проскочит через
    гонку repopulation после invalidate."""
    async with deps.session_factory() as session:
        user = await get_user(session, telegram_id)
        if user is None or user.status != "active":
            deps.user_brokers.pop(telegram_id, None)  # revoked — чистим и кэш
            return None
        if telegram_id in deps.user_brokers:
            return deps.user_brokers[telegram_id]
        if not user.has_token:
            return deps.broker if user.role == "admin" else None
        encrypted = await get_user_token(session, telegram_id)
    try:
        token = decrypt_secret(encrypted, deps.settings.fernet_key)
    except Exception as exc:
        log.error("token_decrypt_failed", user=telegram_id, error=str(exc))
        return None
    broker = TinkoffBroker(token)
    deps.user_brokers[telegram_id] = broker
    return broker


def invalidate_user_broker(deps, telegram_id: int) -> None:
    deps.user_brokers.pop(telegram_id, None)
    deps.portfolio_cache.pop(telegram_id, None)


async def get_cached_portfolio(deps, telegram_id: int,
                               broker) -> PortfolioSnapshot | None:
    """Кэш: (monotonic, snap, fetched_at_utc). При сбое отдаём ПРОШЛЫЙ снимок —
    потребители обязаны смотреть cached_portfolio_age и не выдавать его за живой."""
    cached = deps.portfolio_cache.get(telegram_id)
    if cached and time.monotonic() - cached[0] < PORTFOLIO_TTL_SEC:
        return cached[1]
    try:
        snap = await broker.get_portfolio()
    except Exception as exc:
        log.warning("cached_portfolio_failed", user=telegram_id, error=str(exc))
        return cached[1] if cached else None
    deps.portfolio_cache[telegram_id] = (time.monotonic(), snap,
                                         datetime.now(tz=timezone.utc))
    return snap


def cached_portfolio_age(deps, telegram_id: int) -> timedelta | None:
    """Сколько снимку лет; None — снимка нет (после рестарта)."""
    cached = deps.portfolio_cache.get(telegram_id)
    if not cached:
        return None
    return datetime.now(tz=timezone.utc) - cached[2]
