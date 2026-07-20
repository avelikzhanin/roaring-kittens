# Phase 4b «Мультитенантность» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Друзья подключаются по invite-коду со СВОИМ read-only Tinkoff-токеном и получают свой портфель/дайджест/тезисы/watchlist/алерты/бюджет; владелец становится admin с командами управления; расходы каждого юзера считаются и гейтятся (80% → эконом-модели, 100% → блок тяжёлых циклов).

**Architecture:** Таблицы `users`+`invites`; токены шифруются существующим Fernet; per-user `TinkoffBroker` с кэшем инстансов (admin без токена работает через системный env-токен); **market data остаётся общей** (universe/свечи/скоринг/дивиденды/last_prices — системный брокер). Сквозной учёт расходов через `ContextVar` (`current_user_id`, `budget_mode`) — usage_log получает `user_id`, LLM в эконом-режиме сам подменяет gpt-4o→mini. Все джобы становятся циклами по активным юзерам с токеном; кэш портфелей (TTL 15 мин) спасает 5-минутный impact_scan от шквала Tinkoff-запросов. Онбординг — FSM (код → токен → проверка → шифрование → удаление сообщения с токеном).

**Tech Stack:** существующий, новых зависимостей НЕТ (contextvars, secrets — stdlib; MemoryStorage — в составе aiogram).

**Spec:** §10 (мультитенантность), §12 (users/invites), §13 (бюджеты).

**Verification model:** тесты в GitHub Actions CI; батчи → push → `gh run watch`; деплой `railway up --service app --ci`.

**Зафиксированные решения:**
1. **`calls`/`/track` — общие** (track-record — витрина доверия бота, агрегаты не палят позиции); `calls.asked_by` уже есть → `/history` показывает вызовы СВОЕГО пользователя (admin — все).
2. **`theses`/`watchlists`/алерты/дайджест/sync — строго per-user** (`theses` получает `owner_id`, watchlists уже scoped).
3. **Reflection и `/insights` остаются admin-only** в 4b (уроки из данных admin'а; per-user рефлексия — потом, если появится спрос).
4. **Владелец из `bot_state` мигрирует в `users` как admin** (токен NULL → его брокер = системный env-токен); его существующие тезисы получают его `owner_id`. Идемпотентно на старте.
5. **Гости без инвайта** сохраняют текущее поведение (/ask с лимитом 10/день, без позиции).
6. **Троттлинг алертов — per-chat** (`dict[chat_id, AlertThrottle]`), буфер уже chat-scoped.
7. Экономия при 80% бюджета: карта подмены моделей в LLM (`gpt-4o`→`gpt-4o-mini`); o4-mini/mini не трогаем. 100% → блок /council, авто-комитетов, /seed_retro и spotlight для этого юзера (алерты и /ask-mini остаются).

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── db/users.py             # NEW: users+invites репозиторий, month_spend
├── users_service.py        # NEW: get_user_broker (кэш), get_cached_portfolio (TTL 15м)
├── ai/usage_context.py     # NEW: ContextVar current_user_id / budget_mode
├── ai/llm.py               # MOD: user_id в usage_log, econom-подмена моделей
├── budget.py               # NEW: budget_state + гейт
├── alerts.py               # MOD: per-chat троттлы
├── scheduler.py            # MOD: все джобы — циклы по юзерам
├── digest/morning.py       # MOD: параметр broker
├── positions_sync.py       # MOD: per-user
├── price_watch.py          # MOD: интересы по всем юзерам
├── db/theses.py            # MOD: owner_id во всех функциях
├── deps.py                 # MOD: user_brokers, portfolio_cache, alert_throttles
├── main.py                 # MOD: FSM storage, миграция owner→admin
└── telegram/handlers/
    ├── onboarding.py       # NEW: инвайт-код + FSM приёма токена
    ├── admin.py            # NEW: /admin stats|users|invite|revoke|set_budget
    ├── budget_cmd.py       # NEW: /budget
    └── (portfolio, digest, ask, council, thesis, seed, watchlist, start — MOD гейтов)
db/schema.sql               # MOD: users, invites, theses.owner_id, usage_log.user_id
tests/: test_users_repo.py, test_usage_context.py, test_budget.py, test_users_service.py,
        test_onboarding_logic.py, test_admin_render.py (+MOD существующих theses/alerts)
```

---

### Task 1: Схема — users, invites, owner_id, usage_log.user_id

**Files:**
- Modify: `db/schema.sql`, `src/roaring_kittens/db/tables.py`, `tests/conftest.py`

- [ ] **Step 1: schema.sql (перед bot_state)**

```sql
CREATE TABLE IF NOT EXISTS users (
    telegram_id        BIGINT PRIMARY KEY,
    username           VARCHAR(64),
    role               VARCHAR(20) NOT NULL DEFAULT 'user',    -- 'admin' | 'user'
    status             VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active' | 'revoked'
    tinkoff_token_enc  BYTEA,                                  -- NULL: admin=env-токен, user=без портфеля
    monthly_budget_usd NUMERIC(8,2) NOT NULL DEFAULT 20,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invites (
    code        VARCHAR(16) PRIMARY KEY,
    created_by  BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    redeemed_by BIGINT
);

ALTER TABLE theses ADD COLUMN IF NOT EXISTS owner_id BIGINT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS user_id BIGINT;
```

- [ ] **Step 2: tables.py — колонки и таблицы**

К `theses` добавить `Column("owner_id", BigInteger),` (после `close_reason`); к `usage_log` — `Column("user_id", BigInteger),`. Новые таблицы (перед bot_state):

```python
users = Table(
    "users", metadata,
    Column("telegram_id", BigInteger, primary_key=True),
    Column("username", String(64)),
    Column("role", String(20), nullable=False, server_default=text("'user'")),
    Column("status", String(20), nullable=False, server_default=text("'active'")),
    Column("tinkoff_token_enc", LargeBinary),
    Column("monthly_budget_usd", Numeric(8, 2), nullable=False, server_default=text("20")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

invites = Table(
    "invites", metadata,
    Column("code", String(16), primary_key=True),
    Column("created_by", BigInteger, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("redeemed_by", BigInteger),
)
```

(импорт `LargeBinary` добавить в sqlalchemy-импорты)

- [ ] **Step 3: conftest TRUNCATE — добавить `users, invites`**

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db/tables.py tests/conftest.py
git commit -m "feat: users/invites tables, theses.owner_id, usage_log.user_id"
```

---

### Task 2: Репозиторий users + invites + month_spend

**Files:**
- Create: `src/roaring_kittens/db/users.py`
- Test: `tests/test_users_repo.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_users_repo.py
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.tables import usage_log
from roaring_kittens.db.users import (
    create_invite, get_user, list_active_users, month_spend, redeem_invite,
    set_user_budget, set_user_status, set_user_token, upsert_user,
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


async def test_invites(db_session_factory):
    async with db_session_factory() as session:
        await create_invite(session, "INV-ABC123", created_by=500, ttl_days=7)
        await create_invite(session, "INV-OLD000", created_by=500, ttl_days=7)
        await session.execute(  # состариваем второй
            "UPDATE invites SET expires_at = now() - interval '1 day' "
            "WHERE code = 'INV-OLD000'")
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
```

(в conftest `from sqlalchemy import text` уже не нужен — сырой UPDATE через `session.execute(text(...))`; в тесте использовать `from sqlalchemy import text` и обернуть строку)

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/users.py
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
                                role=role, status=status) \
        .on_conflict_do_update(index_elements=["telegram_id"],
                               set_={"username": username}) \
        .returning(users)
    return _row((await session.execute(stmt)).first())


async def get_user(session: AsyncSession, telegram_id: int) -> UserRecord | None:
    row = (await session.execute(
        select(users).where(users.c.telegram_id == telegram_id))).first()
    return _row(row) if row else None


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
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/db/users.py tests/test_users_repo.py
git commit -m "feat: users and invites repository with per-user month spend"
```

---

### Task 3: Usage-контекст + LLM: user_id и эконом-режим

**Files:**
- Create: `src/roaring_kittens/ai/usage_context.py`
- Modify: `src/roaring_kittens/ai/llm.py`
- Test: `tests/test_usage_context.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_usage_context.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel

from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.usage_context import (
    budget_mode, current_user_id, use_budget_mode, use_user,
)


class Echo(BaseModel):
    answer: str


def _fake_client(tracker):
    async def parse(**kwargs):
        tracker["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=Echo(answer="ok")))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))


async def test_user_id_flows_to_usage_logger_and_econom_swaps_model():
    tracker = {}
    logged = {}

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd,
                       user_id=None):
        logged["user_id"] = user_id
        logged["model"] = model

    llm = LLM(client=_fake_client(tracker), usage_logger=fake_log)
    with use_user(111), use_budget_mode("econom"):
        assert current_user_id.get() == 111
        assert budget_mode.get() == "econom"
        await llm.parse(model="gpt-4o", operation="t",
                        messages=[{"role": "user", "content": "x"}], schema=Echo)
    assert tracker["model"] == "gpt-4o-mini"   # econom подменил
    assert logged["user_id"] == 111
    # вне контекста — дефолты
    assert current_user_id.get() is None and budget_mode.get() == "ok"
    await llm.parse(model="gpt-4o", operation="t",
                    messages=[{"role": "user", "content": "x"}], schema=Echo)
    assert tracker["model"] == "gpt-4o" and logged["user_id"] is None
```

- [ ] **Step 2: Реализовать usage_context.py**

```python
# src/roaring_kittens/ai/usage_context.py
"""Сквозной контекст: чей это LLM-вызов и в каком бюджет-режиме юзер."""
from contextlib import contextmanager
from contextvars import ContextVar

current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
budget_mode: ContextVar[str] = ContextVar("budget_mode", default="ok")  # 'ok'|'econom'


@contextmanager
def use_user(user_id: int | None):
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)


@contextmanager
def use_budget_mode(mode: str):
    token = budget_mode.set(mode)
    try:
        yield
    finally:
        budget_mode.reset(token)
```

- [ ] **Step 3: llm.py — подмена модели и user_id в логгере**

```python
# в src/roaring_kittens/ai/llm.py добавить импорт:
from roaring_kittens.ai.usage_context import budget_mode, current_user_id

ECONOM_MODEL_MAP = {"gpt-4o": "gpt-4o-mini", "gpt-4.1": "gpt-4o-mini"}
```

В `LLM.parse` перед вызовом: `if budget_mode.get() == "econom": model = ECONOM_MODEL_MAP.get(model, model)`; в вызов `self._log_usage(...)` добавить `user_id=current_user_id.get()`.
`make_db_usage_logger._log` — сигнатура `(operation, model, input_tokens, output_tokens, cost_usd, user_id=None)`, в insert добавить `user_id=user_id`.
В `ai/embeddings.py` вызов `self._log_usage(...)` — добавить `user_id=current_user_id.get()` (и импорт). Существующие fake-логгеры в тестах (`test_llm.py`, `test_embedder.py`) — добавить `user_id=None` в сигнатуры фейков и, где проверяются кортежи, не включать его.

- [ ] **Step 4: Push → CI, Commit**

```bash
git add src/roaring_kittens/ai tests/test_usage_context.py tests/test_llm.py tests/test_embedder.py
git commit -m "feat: per-user usage attribution and econom model swap via contextvars"
```

---

### Task 4: budget.py — состояние и гейт

**Files:**
- Create: `src/roaring_kittens/budget.py`
- Test: `tests/test_budget.py`

- [ ] **Step 1: Падающий тест (pure-пороги + IO-обёртка через monkeypatch)**

```python
# tests/test_budget.py
from decimal import Decimal
from types import SimpleNamespace

import roaring_kittens.budget as budget_mod
from roaring_kittens.budget import budget_state, classify_spend


def test_classify_spend_thresholds():
    limit = Decimal("20")
    assert classify_spend(Decimal("0"), limit) == "ok"
    assert classify_spend(Decimal("15.99"), limit) == "ok"
    assert classify_spend(Decimal("16"), limit) == "econom"     # >= 80%
    assert classify_spend(Decimal("19.99"), limit) == "econom"
    assert classify_spend(Decimal("20"), limit) == "blocked"    # >= 100%
    assert classify_spend(Decimal("5"), Decimal("0")) == "blocked"  # нулевой лимит


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_budget_state_reads_user_and_spend(monkeypatch):
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(monthly_budget_usd=Decimal("20"))

    async def fake_spend(session, tg_id):
        return Decimal("17")

    monkeypatch.setattr(budget_mod, "get_user", fake_get_user)
    monkeypatch.setattr(budget_mod, "month_spend", fake_spend)
    deps = SimpleNamespace(session_factory=lambda: FakeSession())
    state, spent, limit = await budget_state(deps, 111)
    assert state == "econom" and spent == Decimal("17") and limit == Decimal("20")
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/budget.py
"""Бюджет-гейт: 80% лимита -> эконом-модели, 100% -> блок тяжёлых циклов."""
from decimal import Decimal

from roaring_kittens.db.users import get_user, month_spend

ECONOM_THRESHOLD = Decimal("0.8")

HEAVY_BLOCKED_MSG = ("💸 Месячный AI-бюджет исчерпан — тяжёлые разборы (комитет) "
                     "заблокированы до 1-го числа. Алерты и лёгкий /ask работают. "
                     "/budget — детали.")


def classify_spend(spent: Decimal, limit: Decimal) -> str:
    if limit <= 0 or spent >= limit:
        return "blocked"
    if spent >= limit * ECONOM_THRESHOLD:
        return "econom"
    return "ok"


async def budget_state(deps, telegram_id: int) -> tuple[str, Decimal, Decimal]:
    """('ok'|'econom'|'blocked', spent, limit). Неизвестный юзер -> blocked."""
    async with deps.session_factory() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            return "blocked", Decimal("0"), Decimal("0")
        spent = await month_spend(session, telegram_id)
    return classify_spend(spent, user.monthly_budget_usd), spent, user.monthly_budget_usd
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/budget.py tests/test_budget.py
git commit -m "feat: per-user budget state with econom/blocked thresholds"
```

---

### Task 5: users_service — per-user брокер и кэш портфелей

**Files:**
- Create: `src/roaring_kittens/users_service.py`
- Modify: `src/roaring_kittens/deps.py`
- Test: `tests/test_users_service.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_users_service.py
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
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/users_service.py
"""Per-user брокеры (кэш инстансов) и TTL-кэш портфелей для частых джобов."""
import time

import structlog

from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.db.users import get_user, get_user_token
from roaring_kittens.security.crypto import decrypt_secret

log = structlog.get_logger()

PORTFOLIO_TTL_SEC = 900  # 15 минут


async def get_user_broker(deps, telegram_id: int):
    """Брокер юзера: admin без токена -> системный; user -> свой (кэш); нет/revoked -> None."""
    if telegram_id in deps.user_brokers:
        return deps.user_brokers[telegram_id]
    async with deps.session_factory() as session:
        user = await get_user(session, telegram_id)
        if user is None or user.status != "active":
            return None
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
    cached = deps.portfolio_cache.get(telegram_id)
    if cached and time.monotonic() - cached[0] < PORTFOLIO_TTL_SEC:
        return cached[1]
    try:
        snap = await broker.get_portfolio()
    except Exception as exc:
        log.warning("cached_portfolio_failed", user=telegram_id, error=str(exc))
        return cached[1] if cached else None
    deps.portfolio_cache[telegram_id] = (time.monotonic(), snap)
    return snap
```

`deps.py` — три поля-кэша (после alert_throttle):

```python
    user_brokers: dict = field(default_factory=dict)
    portfolio_cache: dict = field(default_factory=dict)
    alert_throttles: dict = field(default_factory=dict)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/users_service.py src/roaring_kittens/deps.py tests/test_users_service.py
git commit -m "feat: per-user brokers with instance cache and TTL portfolio cache"
```

---

### Task 6: alerts — троттлинг per-chat

**Files:**
- Modify: `src/roaring_kittens/alerts.py`, `tests/test_alerts.py`

- [ ] **Step 1: Правка send_alert (deps.alert_throttle → per-chat из deps.alert_throttles)**

```python
        if not deps.alert_throttles.setdefault(chat_id, AlertThrottle()).allow(now):
```

(строку `if not deps.alert_throttle.allow(now):` заменить; поле `alert_throttle` из Deps удалить — единственный потребитель здесь; из test_alerts фикстуру `_deps` перевести на `alert_throttles={}`)

- [ ] **Step 2: Обновить tests/test_alerts.py**

В `_deps`: `alert_throttle=AlertThrottle(max_per_hour=3)` → `alert_throttles={}` и добавить тест изоляции:

```python
async def test_throttle_is_per_chat(monkeypatch):
    async def fake_push(session, chat_id, payload):
        pass

    monkeypatch.setattr(alerts_mod, "push_alert", fake_push)
    monkeypatch.setattr(alerts_mod, "_now_local", lambda deps: _msk(12))
    bot = SimpleNamespace(send_message=AsyncMock())
    deps = _deps(_msk(12))
    for _ in range(3):
        assert await send_alert(deps, bot, 42, "x") == "sent"
    assert await send_alert(deps, bot, 42, "x") == "buffered"   # 42 исчерпан
    assert await send_alert(deps, bot, 777, "x") == "sent"      # у 777 свой лимит
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/alerts.py src/roaring_kittens/deps.py tests/test_alerts.py
git commit -m "feat: per-chat alert throttling"
```

---

### Task 7: theses.owner_id во всех функциях + миграция owner→admin на старте

**Files:**
- Modify: `src/roaring_kittens/db/theses.py`, `src/roaring_kittens/main.py`, `tests/test_theses_repo.py`

- [ ] **Step 1: theses.py — скоупинг**

- `ThesisRecord` + поле `owner_id: int | None = None` (последним, default); `_row` добавляет `owner_id=r.owner_id`.
- `save_thesis(..., owner_id: int)` — обязательный kwarg; supersede-UPDATE получает условие `theses.c.owner_id == owner_id`; insert values + owner_id.
- `get_active_thesis(session, ticker, owner_id)`, `get_active_theses(session, owner_id=None)` (None — все, для валидатора), `get_recently_closed(session, days, owner_id, ...)`, `get_recently_deleted_tickers(session, owner_id, days=30)` — фильтр `owner_id` где передан.
- Все вызовы по кодовой базе обновить (positions_sync, scheduler.validate_theses — там `get_active_theses(session)` остаётся все-пользовательским, price_watch — все, reflection — owner admin'а, handlers/thesis.py — свои).

- [ ] **Step 2: main.py — миграция (после claim_owner-блока)**

```python
    from sqlalchemy import text as sa_text

    from roaring_kittens.db.owner import fetch_owner_id
    from roaring_kittens.db.users import get_user, upsert_user

    owner_id = await fetch_owner_id(session_factory)
    if owner_id is not None:
        async with session_factory() as session:
            if await get_user(session, owner_id) is None:
                await upsert_user(session, owner_id, role="admin")
                log.info("owner_migrated_to_admin", owner=owner_id)
            await session.execute(sa_text(
                "UPDATE theses SET owner_id = :o WHERE owner_id IS NULL"),
                {"o": owner_id})
            await session.commit()
```

- [ ] **Step 3: Обновить tests/test_theses_repo.py — все save_thesis получают `owner_id=42`, выборки — с owner_id; добавить тест изоляции:**

```python
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
        assert mine.thesis == "мой" and theirs.thesis == "чужой"  # не супersede друг друга
        assert len(await get_active_theses(session)) == 2          # None = все
```

- [ ] **Step 4: Push → CI, Commit**

```bash
git add src/roaring_kittens/db/theses.py src/roaring_kittens/main.py tests/test_theses_repo.py src/roaring_kittens/positions_sync.py src/roaring_kittens/scheduler.py src/roaring_kittens/reflection.py src/roaring_kittens/telegram/handlers/thesis.py src/roaring_kittens/price_watch.py
git commit -m "feat: per-owner theses scoping with owner migration at startup"
```

---

### Task 8: Онбординг — инвайт-код + FSM приёма токена

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/onboarding.py`
- Modify: `src/roaring_kittens/main.py` (FSM storage), `src/roaring_kittens/telegram/handlers/__init__.py`
- Test: `tests/test_onboarding_logic.py`

- [ ] **Step 1: Падающий тест (pure-валидаторы)**

```python
# tests/test_onboarding_logic.py
from roaring_kittens.telegram.handlers.onboarding import (
    generate_invite_code, looks_like_invite, looks_like_tinkoff_token,
)


def test_invite_code_format_roundtrip():
    code = generate_invite_code()
    assert looks_like_invite(code) is True
    assert looks_like_invite("inv-abc123") is True   # регистр не важен
    assert looks_like_invite("HELLO") is False
    assert looks_like_invite("INV-TOOLONG123") is False


def test_token_shape():
    assert looks_like_tinkoff_token("t.AbCdEf123456789012345") is True
    assert looks_like_tinkoff_token("привет") is False
    assert looks_like_tinkoff_token("t.short") is False
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/telegram/handlers/onboarding.py
"""Онбординг друга: инвайт-код -> инструкция -> приём токена (сообщение удаляется)."""
import re
import secrets

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from roaring_kittens.db.users import redeem_invite, set_user_token, upsert_user
from roaring_kittens.deps import Deps
from roaring_kittens.security.crypto import encrypt_secret
from roaring_kittens.users_service import get_user_broker, invalidate_user_broker

log = structlog.get_logger()
router = Router()

INVITE_RE = re.compile(r"^INV-[A-F0-9]{6}$", re.IGNORECASE)
TOKEN_RE = re.compile(r"^t\.[A-Za-z0-9_\-]{16,}$")


class Onboarding(StatesGroup):
    waiting_token = State()


def generate_invite_code() -> str:
    return "INV-" + secrets.token_hex(3).upper()


def looks_like_invite(text: str) -> bool:
    return bool(INVITE_RE.match(text.strip()))


def looks_like_tinkoff_token(text: str) -> bool:
    return bool(TOKEN_RE.match(text.strip()))


TOKEN_INSTRUCTIONS = (
    "✅ Код принят! Чтобы я работал с ТВОИМ портфелем, нужен токен Tinkoff Invest API:\n\n"
    "1. Открой tbank.ru/invest → Настройки → «Токен Tinkoff Invest API»\n"
    "2. Тип: <b>«Только чтение»</b> (я по дизайну не совершаю сделок)\n"
    "3. Скопируй токен (вида <code>t.XXXX…</code>) и пришли сюда одним сообщением\n\n"
    "🔒 Токен шифруется, сообщение с ним я сразу удалю. Передумал — /cancel."
)


@router.message(F.text.regexp(r"(?i)^INV-[A-F0-9]{6}$"))
async def handle_invite_code(message: Message, deps: Deps, state: FSMContext) -> None:
    code = message.text.strip().upper()
    async with deps.session_factory() as session:
        ok = await redeem_invite(session, code, message.from_user.id)
        if ok:
            await upsert_user(session, message.from_user.id,
                              username=message.from_user.username)
        await session.commit()
    if not ok:
        await message.answer("❌ Код не найден, просрочен или уже использован.")
        return
    await state.set_state(Onboarding.waiting_token)
    await message.answer(TOKEN_INSTRUCTIONS)


@router.message(Onboarding.waiting_token, F.text == "/cancel")
async def cancel_onboarding(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок, отменил. Аккаунт создан без портфеля — /ask доступен. "
                         "Токен можно прислать позже, начав с инвайт-кода заново.")


@router.message(Onboarding.waiting_token)
async def handle_token(message: Message, deps: Deps, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not looks_like_tinkoff_token(text):
        await message.answer("Не похоже на токен (ожидаю <code>t.XXXX…</code>). "
                             "Попробуй ещё раз или /cancel.")
        return
    try:
        await message.delete()  # токен не должен остаться в чате
    except Exception as exc:
        log.warning("token_message_delete_failed", error=str(exc))
    encrypted = encrypt_secret(text, deps.settings.fernet_key)
    async with deps.session_factory() as session:
        await set_user_token(session, message.from_user.id, encrypted)
        await session.commit()
    invalidate_user_broker(deps, message.from_user.id)
    broker = await get_user_broker(deps, message.from_user.id)
    try:
        snap = await broker.get_portfolio()
        positions = ", ".join(p.ticker for p in snap.positions) or "пусто"
    except Exception as exc:
        log.error("onboarding_portfolio_failed", error=str(exc))
        async with deps.session_factory() as session:
            await set_user_token(session, message.from_user.id, None)
            await session.commit()
        invalidate_user_broker(deps, message.from_user.id)
        await message.answer("❌ Токен не сработал (проверь, что он Invest API и активен). "
                             "Пришли другой или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"🎉 Подключился к твоему счёту! Позиции: {positions}.\n\n"
        f"Тебе доступно: /portfolio /digest /ask /thesis /watch /budget.\n"
        f"Утренний дайджест — сам в 9:00 МСК. Тезисы для позиций ≥5% появятся "
        f"после ближайшей утренней сверки.")
```

`main.py`: `from aiogram.fsm.storage.memory import MemoryStorage` и `dp = Dispatcher(deps=deps, storage=MemoryStorage())`.
`handlers/__init__.py`: подключить `onboarding.router` ПЕРВЫМ (state-фильтры должны видеть сообщения раньше catch-all-хендлеров).

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/telegram src/roaring_kittens/main.py tests/test_onboarding_logic.py
git commit -m "feat: invite-code onboarding with FSM token intake and verification"
```

---

### Task 9: Admin-команды + /budget

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/admin.py`, `src/roaring_kittens/telegram/handlers/budget_cmd.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`
- Test: `tests/test_admin_render.py`

- [ ] **Step 1: Падающий тест рендера**

```python
# tests/test_admin_render.py
from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.db.users import UserRecord
from roaring_kittens.telegram.handlers.admin import format_users
from roaring_kittens.telegram.handlers.budget_cmd import format_budget

NOW = datetime.now(tz=timezone.utc)


def _u(tg, role="user", token=True):
    return UserRecord(telegram_id=tg, username=f"u{tg}", role=role, status="active",
                      has_token=token, monthly_budget_usd=Decimal("20"), created_at=NOW)


def test_format_users_shows_roles_and_spend():
    text = format_users([_u(500, role="admin", token=False), _u(111)],
                        {500: Decimal("3.5"), 111: Decimal("17.2")})
    assert "500" in text and "admin" in text
    assert "111" in text and "17.2" in text and "20" in text


def test_format_budget_states():
    assert "🟢" in format_budget("ok", Decimal("2"), Decimal("20"))
    assert "🟡" in format_budget("econom", Decimal("17"), Decimal("20"))
    assert "🔴" in format_budget("blocked", Decimal("20"), Decimal("20"))
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/telegram/handlers/admin.py
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.db.users import (
    UserRecord, create_invite, get_user, list_active_users, month_spend,
    set_user_budget, set_user_status,
)
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.handlers.onboarding import generate_invite_code
from roaring_kittens.users_service import invalidate_user_broker

router = Router()

USAGE = ("/admin invite — создать код\n"
         "/admin users — юзеры и расходы\n"
         "/admin revoke ID — отключить\n"
         "/admin set_budget ID USD — лимит")


def format_users(users: list[UserRecord], spend: dict[int, Decimal]) -> str:
    lines = ["👥 <b>Пользователи:</b>", ""]
    for u in users:
        token = "🔑" if u.has_token else "—"
        lines.append(f"{u.telegram_id} @{u.username or '?'} [{u.role}] {token} "
                     f"${spend.get(u.telegram_id, Decimal('0'))}/"
                     f"${u.monthly_budget_usd}")
    return "\n".join(lines)


async def _require_admin(message: Message, deps: Deps) -> bool:
    async with deps.session_factory() as session:
        user = await get_user(session, message.from_user.id)
    if user is None or user.role != "admin":
        await message.answer("🔒 Только для admin.")
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    if not await _require_admin(message, deps):
        return
    args = (command.args or "").split()
    if not args:
        await message.answer(USAGE)
        return
    sub = args[0]
    async with deps.session_factory() as session:
        if sub == "invite":
            code = generate_invite_code()
            await create_invite(session, code, created_by=message.from_user.id)
            await session.commit()
            await message.answer(f"🎟 Код (7 дней): <code>{code}</code>\n"
                                 f"Друг просто отправляет его боту.")
        elif sub == "users" or sub == "stats":
            users = await list_active_users(session)
            spend = {u.telegram_id: await month_spend(session, u.telegram_id)
                     for u in users}
            await message.answer(format_users(users, spend))
        elif sub == "revoke" and len(args) > 1 and args[1].isdigit():
            await set_user_status(session, int(args[1]), "revoked")
            await session.commit()
            invalidate_user_broker(deps, int(args[1]))
            await message.answer(f"⛔️ {args[1]} отключён.")
        elif sub == "set_budget" and len(args) > 2 and args[1].isdigit():
            await set_user_budget(session, int(args[1]), Decimal(args[2]))
            await session.commit()
            await message.answer(f"💰 Бюджет {args[1]} = ${args[2]}/мес.")
        else:
            await message.answer(USAGE)
```

```python
# src/roaring_kittens/telegram/handlers/budget_cmd.py
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.budget import budget_state
from roaring_kittens.deps import Deps

router = Router()

STATE_ICON = {"ok": "🟢", "econom": "🟡", "blocked": "🔴"}
STATE_TEXT = {"ok": "всё доступно",
              "econom": "эконом-режим: разборы на облегчённых моделях",
              "blocked": "тяжёлые разборы заблокированы до 1-го числа"}


def format_budget(state: str, spent: Decimal, limit: Decimal) -> str:
    return (f"{STATE_ICON[state]} <b>AI-бюджет:</b> ${spent} из ${limit} за месяц\n"
            f"{STATE_TEXT[state]}")


@router.message(Command("budget"))
async def cmd_budget(message: Message, deps: Deps) -> None:
    state, spent, limit = await budget_state(deps, message.from_user.id)
    await message.answer(format_budget(state, spent, limit))
```

`handlers/__init__.py`: + `admin`, `budget_cmd` роутеры.

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/telegram tests/test_admin_render.py
git commit -m "feat: /admin suite and /budget command"
```

---

### Task 10: Гейты команд: users вместо owner + бюджет в /council и /ask

**Files:**
- Modify: `telegram/handlers/{portfolio,digest,ask,council,thesis,seed,watchlist,track,start}.py`

- [ ] **Step 1: Общий помощник (в `db/users.py` дописать)**

```python
async def get_active_user(session: AsyncSession, telegram_id: int) -> UserRecord | None:
    u = await get_user(session, telegram_id)
    return u if u is not None and u.status == "active" else None
```

- [ ] **Step 2: Пер-хендлерные правки (паттерн один — привожу целиком для portfolio, остальные аналогично)**

`portfolio.py` — вместо owner-гейта: активный юзер с брокером; свой портфель:

```python
from roaring_kittens.users_service import get_user_broker

@router.message(Command("portfolio"))
@router.message(F.text == "📊 Портфель")
async def cmd_portfolio(message: Message, deps: Deps) -> None:
    broker = await get_user_broker(deps, message.from_user.id)
    if broker is None:
        await message.answer("🔒 Портфель доступен после подключения своего "
                             "Tinkoff-токена (нужен инвайт-код от владельца).")
        return
    snap = await broker.get_portfolio()
    await message.answer(format_portfolio(snap))
```

Аналогично:
- `digest.py`: `broker = await get_user_broker(...)`; `run_morning_digest(deps, bot, chat_id, broker)` (см. Task 11).
- `ask.py`: `build_position_note` → принимает broker юзера (`get_user_broker`; None → note=None); гостевой лимитер остаётся для НЕзарегистрированных (`get_active_user is None`); зарегистрированный оборачивает вызов в `use_user(id)` + `use_budget_mode(state if econom)`.
- `council.py`: гейт = активный юзер с брокером; перед запуском `state,_,_ = await budget_state(deps, uid)`; `blocked` → `HEAVY_BLOCKED_MSG`; запуск в `with use_user(uid), use_budget_mode("econom" if state=="econom" else "ok"):`; `run_council_flow(..., broker=broker)` — контекст позиции от СВОЕГО брокера (см. Task 11); кнопки как раньше.
- `thesis.py`: все выборки/сохранения с `owner_id=message.from_user.id`; гейт — активный юзер; `/insights` — role=='admin'.
- `seed.py`: гейт активный юзер с брокером; blocked-бюджет → отказ; `use_user`; позиции — свой брокер; save_call.asked_by уже его.
- `watchlist.py`: `_owner_or_none` → `_active_user_or_none` (без требования токена — watch можно и без портфеля).
- `track.py`: без изменений (общий).
- `/history` в `thesis.py`: фильтр `asked_by`: добавить в `get_ticker_history(session, ticker, limit, asked_by=None)` необязательный фильтр; хендлер передаёт свой id (admin — None).
- `start.py`: приветствие: если юзер в users — статус/подсказки; иначе прежний owner-claim + строка «Есть инвайт-код? Просто пришли его сюда (формат INV-XXXXXX)».

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/telegram src/roaring_kittens/db/users.py src/roaring_kittens/db/calls.py
git commit -m "feat: user-based gates with budget enforcement across commands"
```

---

### Task 11: Параметризация ядра: broker в digest/context/runner

**Files:**
- Modify: `digest/morning.py`, `committee/context.py`, `committee/runner.py`, `positions_sync.py`, `telegram/handlers/ask.py`

- [ ] **Step 1: Сигнатуры**

- `run_morning_digest(deps, bot, chat_id, broker)` — все `deps.broker.get_portfolio()` → `broker.get_portfolio()`; `build_spotlight(deps, position, asked_by)` не меняется (свечи — системные `deps.broker`).
- `build_council_context(deps, instrument, asked_by, today, include_memory=True, broker=None)`: блок позиции — `broker` (если None → позиции нет); **market data (свечи/дивиденды) остаются на `deps.broker`**.
- `run_council_flow(deps, instrument, asked_by, ctx=None, on_stage=None, broker=None)` — прокидывает broker в build_council_context.
- `positions_sync.sync_positions(deps, bot)` → цикл по юзерам (Task 12), внутренняя `_sync_user(deps, bot, user_id, broker)` использует user-broker для snap, `deps.broker` для свечей realized return; `save_thesis(..., owner_id=user_id)`; suppressed/active — по owner_id.
- `ask.py` `build_position_note(deps, ticker)` → `build_position_note(broker, ticker)` (fetch snap с переданного брокера).

- [ ] **Step 2: Обновить существующие тесты сигнатур** (`test_council_context.py` — параметр broker=None по умолчанию не ломает; digest-тесты builder-функций не трогаются).

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/digest src/roaring_kittens/committee src/roaring_kittens/positions_sync.py src/roaring_kittens/telegram/handlers/ask.py
git commit -m "refactor: broker parameterization for per-user portfolio context"
```

---

### Task 12: Джобы — циклы по активным юзерам

**Files:**
- Modify: `src/roaring_kittens/scheduler.py`, `src/roaring_kittens/positions_sync.py`, `src/roaring_kittens/price_watch.py`, `src/roaring_kittens/reflection.py`

- [ ] **Step 1: scheduler.py**

- `morning_digest_job`: цикл `for u in await list_active_users(session)` → `broker = await get_user_broker(deps, u.telegram_id)`; если broker None — только дренаж буфера юзера (если есть); иначе дренаж + `with use_user(u.telegram_id): await run_morning_digest(deps, bot, u.telegram_id, broker)`; ошибки одного юзера не роняют остальных (try/except вокруг тела цикла).
- `validate_theses`: тезисы уже всех юзеров (`get_active_theses(session)`); адресат — `thesis.owner_id` (fallback на admin, если None); авто-комитет: `state,_,_ = budget_state(deps, owner)` → blocked ⇒ только notify (critical), не council; запуск `with use_user(owner), use_budget_mode(...)`; `run_council_flow(..., broker=await get_user_broker(deps, owner))`.
- `impact_scan`: цикл по активным юзерам с брокером: interest = `get_cached_portfolio` ∪ их watchlist − их thesis-тикеры; **классификация новостей по тикеру кэшируется в рамках прогона** (`checked: dict[str, ImpactCheck]`), уведомления — каждому заинтересованному юзеру; council-ветка — от имени юзера с его budget-гейтом (blocked ⇒ notify-only).
- `weekly_reflection_job`: без изменений по сути, но явное `admin`-скоупирование: `closed = get_recently_closed(session, days=7, owner_id=admin_id)`; отправка админу.

- [ ] **Step 2: positions_sync.py — обёртка**

```python
async def sync_positions(deps, bot) -> None:
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    for u in users:
        broker = await get_user_broker(deps, u.telegram_id)
        if broker is None:
            continue
        try:
            with use_user(u.telegram_id):
                await _sync_user(deps, bot, u.telegram_id, broker)
        except Exception as exc:
            log.error("sync_user_failed", user=u.telegram_id, error=str(exc))
```

`_sync_user` — прежнее тело `sync_positions` c заменами: `owner_id=user_id`, `snap = await broker.get_portfolio()`, theses/suppressed/save — c owner_id, уведомления на `user_id`.

- [ ] **Step 3: price_watch.py — интересы всех юзеров**

`figi_by_ticker` собирать per-user (`interests: dict[user_id, dict[ticker, figi]]`), last_prices — одним батчем по объединению figi (системный брокер), алерты — каждому юзеру по его интересам, дедуп-ключ `(date, user_id, ticker)` (расширить `DayMoveDeduper.allow(user_id, ticker, today)` и тест).

- [ ] **Step 4: Push → CI, Commit**

```bash
git add src/roaring_kittens/scheduler.py src/roaring_kittens/positions_sync.py src/roaring_kittens/price_watch.py src/roaring_kittens/reflection.py tests/test_price_watch.py
git commit -m "feat: all jobs iterate active users with per-user brokers and budgets"
```

---

### Task 13: README, деплой, E2E

- [ ] **Step 1: README — шапка «Сейчас (Phase 4b)» + раздел**

```markdown
## Мультитенантность (Phase 4b)

Друг получает инвайт-код (`/admin invite`), отправляет его боту, подключает СВОЙ
read-only Tinkoff-токен (шифруется Fernet, сообщение с токеном удаляется) — и
получает свой портфель/дайджест/тезисы/watchlist/алерты. Расходы каждого юзера
пишутся в usage_log (user_id через contextvar); при 80% месячного бюджета —
эконом-модели (gpt-4o→mini), при 100% — блок комитетов до 1-го числа (/budget).
Market data общая (системный токен), track-record общий, /insights и рефлексия —
у admin. Admin: /admin invite|users|revoke|set_budget.
```

- [ ] **Step 2: Deploy** — `railway up --service app --ci`

- [ ] **Step 3: MANUAL — E2E-чеклист**

- [ ] Владелец после деплоя: /portfolio и /council работают как раньше (миграция admin прошла — в логах owner_migrated_to_admin при первом старте)
- [ ] `/admin invite` → код; с ВТОРОГО Telegram-аккаунта: отправить код → инструкция → прислать токен → сообщение с токеном исчезло → «🎉 Подключился, позиции: …»
- [ ] У друга: /portfolio показывает ЕГО позиции; /thesis пуст; утром — свой дайджест и авто-тезисы; /watch работает
- [ ] Изоляция: /thesis друга не видит тезисы владельца и наоборот; /history показывает только свои разборы
- [ ] /budget у обоих; `/admin set_budget <id> 1` другу → его /council блокируется с 💸-сообщением, /ask работает
- [ ] `/admin revoke <id>` → у друга команды закрыты
- [ ] `/admin users` — таблица с расходами
- [ ] usage_log: новые строки с user_id

- [ ] **Step 4: Тег**

```bash
git tag phase-4b && git push origin phase-4b
```

---

## Self-review checklist (выполнен при написании)

- **Spec §10 coverage:** users+encrypted tokens ✅ (T1-T2, T8) · invites TTL 7д ✅ (T2, T9) · onboarding с удалением токен-сообщения и проверкой ✅ (T8) · per-user изоляция портфель/дайджест/тезисы/watchlist/алерты ✅ (T7, T10-T12) · budget 80/100 + /budget ✅ (T3-T4, T10) · admin-команды ✅ (T9) · guests сохраняют /ask ✅ (T10) · owner→admin миграция ✅ (T7)
- **Типы согласованы:** `UserRecord` (T2) в T5/T9/T12; `get_user_broker/get_cached_portfolio/invalidate_user_broker` (T5) в T8/T9/T10/T12; `use_user/use_budget_mode` (T3) в T10/T12; `budget_state/classify_spend/HEAVY_BLOCKED_MSG` (T4) в T10/T12; `save_thesis(owner_id=)` (T7) везде; `run_morning_digest(..., broker)` и `run_council_flow(..., broker=)` (T11) в T10/T12
- **Placeholder scan:** в T10/T12 модификации описаны паттерном с полным кодом ключевых мест — исполняющий агент (я, с полным контекстом кода) закрывает механику; новые модули — код целиком ✅
- **Приватность:** токены только шифрованными, сообщение удаляется, decrypt только в get_user_broker; календарь угроз: revoked → invalidate кэша ✅
- **Cost:** portfolio TTL-кэш 15м для 5-мин impact_scan; классификация новости 1 раз на тикер за прогон; budget-гейт на всех тяжёлых путях ✅
