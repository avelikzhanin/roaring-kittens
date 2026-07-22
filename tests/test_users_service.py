import time
from decimal import Decimal
from types import SimpleNamespace

import roaring_kittens.users_service as us_mod
from cryptography.fernet import Fernet

from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.security.crypto import encrypt_secret
from roaring_kittens.users_service import get_cached_portfolio, get_user_broker

KEY = Fernet.generate_key().decode()


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _deps():
    return SimpleNamespace(
        settings=SimpleNamespace(fernet_key=KEY),
        session_factory=lambda: FakeSession(),
        broker="SYSTEM_BROKER",
        user_brokers={}, portfolio_cache={},
    )


async def test_admin_without_token_gets_system_broker(monkeypatch):
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(role="admin", status="active", has_token=False)

    async def fake_token(session, tg_id):
        return None

    monkeypatch.setattr(us_mod, "get_user", fake_get_user)
    monkeypatch.setattr(us_mod, "get_user_token", fake_token)
    assert await get_user_broker(_deps(), 500) == "SYSTEM_BROKER"


async def test_user_with_token_gets_cached_own_broker(monkeypatch):
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(role="user", status="active", has_token=True)

    async def fake_token(session, tg_id):
        return encrypt_secret("t.secret", KEY)

    created = []

    class FakeBroker:
        def __init__(self, token):
            created.append(token)

    monkeypatch.setattr(us_mod, "get_user", fake_get_user)
    monkeypatch.setattr(us_mod, "get_user_token", fake_token)
    monkeypatch.setattr(us_mod, "TinkoffBroker", FakeBroker)
    deps = _deps()
    b1 = await get_user_broker(deps, 111)
    b2 = await get_user_broker(deps, 111)
    assert b1 is b2 and created == ["t.secret"]  # инстанс кэширован


async def test_user_without_token_or_revoked_gets_none(monkeypatch):
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(role="user", status="revoked", has_token=True)

    monkeypatch.setattr(us_mod, "get_user", fake_get_user)
    assert await get_user_broker(_deps(), 111) is None


async def test_revoked_user_does_not_get_stale_cached_broker(monkeypatch):
    """Статус проверяется ДО кэша: revoke мгновенно отрубает даже закэшированного."""
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(role="user", status="revoked", has_token=True)

    monkeypatch.setattr(us_mod, "get_user", fake_get_user)
    deps = _deps()
    deps.user_brokers[111] = "STALE_BROKER"   # гонка repopulation
    assert await get_user_broker(deps, 111) is None
    assert 111 not in deps.user_brokers        # кэш вычищен


async def test_portfolio_cache_ttl(monkeypatch):
    calls = {"n": 0}

    class FakeBroker:
        async def get_portfolio(self):
            calls["n"] += 1
            return PortfolioSnapshot(total_value=Decimal("1"), positions=[])

    deps = _deps()
    broker = FakeBroker()
    snap1 = await get_cached_portfolio(deps, 111, broker)
    snap2 = await get_cached_portfolio(deps, 111, broker)
    assert calls["n"] == 1 and snap1 is snap2          # из кэша
    deps.portfolio_cache[111] = (time.monotonic() - 9999, snap1)  # состарили
    await get_cached_portfolio(deps, 111, broker)
    assert calls["n"] == 2                              # TTL истёк — перезапрос
