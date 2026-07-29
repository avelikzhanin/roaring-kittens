# Phase 5 «Сделки» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замкнуть петлю «идея → принятие → покупка → мониторинг уровней → сигнал выхода → результат»: бот присылает конкретные идеи сделок с размером и уровнями, авто-детектит покупку по read-only счёту, следит за целью/выходом и ведёт понятный список сделок (/deals) — то, на чём юзер реально зарабатывает.

**Architecture:** Таблица `deals` (proposed→accepted→active→closed / declined / expired) с `deal_no BIGSERIAL` для «№12». Идеи рождаются ТОЛЬКО из approved-BUY вердиктов комитета (все три пути: /council, авто-комитет валидатора, impact) для тикера, которого у юзера нет; PM расширяется полями target_price/exit_price с кодовым санити-чеком и детерминированным фолбэком. Сайзинг — risk-based: риск 1% портфеля ÷ (вход−выход), кап 15% концентрации (лимит Risk Manager), минимум 1 лот (лот приходит из Tinkoff list_shares). Активация и закрытие — через positions_sync (изменения реального счёта); мониторинг уровней — в price_watch (без LLM, бесплатно). Терминология: «Инвалидация» → «🛑 Продаём если». Новости: + Интерфакс как источник фактов, Смартлаб понижается до crowd-only (только сентимент комитета).

**Tech Stack:** существующий; новых зависимостей НЕТ.

**Verification model:** тесты в GitHub Actions CI; батчи → push → `gh run watch`; деплой `railway up --service app --ci`.

**Зафиксированные решения:**
1. **Частота идей** — «реалистично»: только approved BUY комитета, guard ≤1 предложение на (юзер, тикер) за 7 дней, предложение протухает через 48 ч (lazy-expire при тапе/рендере, без новой джобы).
2. **Сайзинг** — риск-подход: `qty = 1% × total_value ÷ (entry − exit)`, кап 15% стоимости портфеля (тот же лимит концентрации, что у Risk Manager), минимум 1 лот; при слишком маленьком портфеле предлагаем 1 лот с честной припиской о повышенном риске. Наличных бот не видит и не гадает — приписка «исходя из портфеля, который я вижу»; фактический размер берётся со счёта после покупки.
3. **Уровни** — их даёт PM (новые поля схемы), код проверяет разумность (exit на 3–20% ниже входа, target ≥3% выше), иначе фолбэк: exit = −7%, target = +14% от last_close.
4. **Конвертация позиций** — ЛЮБАЯ позиция без активной сделки при утренней сверке становится `converted`-сделкой (вход = avg_price со счёта, уровни от текущей цены: −7%/+14%). Покрывает и текущие SBER/VTBR (решение юзера «да»), и будущие самостоятельные покупки.
5. **Закрытие** — авто при исчезновении позиции со счёта (цена закрытия = last price на момент обнаружения) или кнопкой [Продал]. Сравнение с IMOEX per-deal в v1 НЕ делаем (YAGNI — глобальное сравнение остаётся в /track).
6. **Мониторинг уровней** — price_watch: last ≤ exit → 🛑 сигнал выхода (critical=False? нет: exit-сигнал шлём critical=True — это то, ради чего всё), last ≥ target → 🎯 фиксация прибыли (обычный). Кнопки [Продал] [Держу — пауза 3 дня]. Дедуп 1 сигнал/тип/день/сделка (in-memory, паттерн DayMoveDeduper), плюс `signal_muted_until`.
7. **Регуляторика** — в каждой идее строка «_Не является индивидуальной инвестиционной рекомендацией._»; фаза остаётся f&f-only.
8. **Новости** — `SOURCES` += Интерфакс (https://www.interfax.ru/rss.asp); `CROWD_SOURCES = {"smartlab"}` переезжает в news/sources.py; дайджест, validate_theses и impact_scan фильтруют crowd-источники из фактов; сентимент-аналитик комитета продолжает читать Смартлаб (сплит уже есть в context.py). Работоспособность фида проверяется по логам `news_polled source=interfax` после деплоя; при мусоре/недоступности — откат одной строкой.
9. **Меню** — `[[📊 Портфель, 💼 Сделки], [📅 Дайджест, 💡 Спросить], [❓ Помощь]]`.

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── db/deals.py             # NEW: репозиторий сделок
├── sizing.py               # NEW: risk-based размер сделки
├── deals_service.py        # NEW: уровни, текст идеи, propose/activate/close/convert
├── committee/schemas.py    # MOD: Proposal + target_price/exit_price
├── committee/manager.py    # MOD: промпт PM — давать уровни
├── committee/render.py     # MOD: «Продаём если» вместо «Инвалидация»
├── broker/tinkoff_client.py# MOD: list_shares → + lot
├── universe/universe.py    # MOD: Instrument.lot
├── positions_sync.py       # MOD: активация/закрытие/конвертация сделок
├── price_watch.py          # MOD: сигналы по уровням active-сделок
├── digest/morning.py       # MOD: секция «Твои сделки»
├── news/sources.py         # MOD: interfax, CROWD_SOURCES
├── committee/context.py    # MOD: CROWD_SOURCES импорт из news.sources
├── scheduler.py            # MOD: crowd-фильтр фактов; хук идеи в авто-комитетах
└── telegram/handlers/
    ├── deals.py            # NEW: /deals + колбэки deal_take/skip/sold/hold
    ├── council.py          # MOD: хук идеи после approved BUY
    ├── thesis.py           # MOD: терминология
    └── start.py            # MOD: меню + help
db/schema.sql               # MOD: deals
tests/: test_deals_repo.py, test_sizing.py, test_deal_levels.py, test_deal_render.py
        (+MOD test_universe*, test_price_watch, test_council_*)
```

---

### Task 1: Схема — deals

**Files:**
- Modify: `db/schema.sql`, `src/roaring_kittens/db/tables.py`, `tests/conftest.py`

- [ ] **Step 1: schema.sql (после invites)**

```sql
CREATE TABLE IF NOT EXISTS deals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_no      BIGSERIAL,                              -- человекочитаемый «№12»
    user_id      BIGINT NOT NULL,
    ticker       VARCHAR(20) NOT NULL,
    figi         VARCHAR(20) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'proposed',-- proposed|accepted|active|closed|declined|expired
    source       VARCHAR(20) NOT NULL,                   -- 'council' | 'converted'
    council_run_id UUID,
    proposed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    entry_suggested NUMERIC,
    qty_suggested   NUMERIC,
    entry_actual    NUMERIC,
    qty_actual      NUMERIC,
    opened_at    TIMESTAMPTZ,
    target_price NUMERIC NOT NULL,
    exit_price   NUMERIC NOT NULL,
    exit_note    TEXT NOT NULL,                          -- «Продаём если …» (новостная часть)
    signal_muted_until TIMESTAMPTZ,
    closed_at    TIMESTAMPTZ,
    close_reason TEXT,
    exit_actual  NUMERIC,
    result_pct   NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_deals_user_status ON deals (user_id, status);
```

- [ ] **Step 2: tables.py (после invites)**

```python
deals = Table(
    "deals", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("deal_no", BigInteger, server_default=text("nextval('deals_deal_no_seq')")),
    Column("user_id", BigInteger, nullable=False),
    Column("ticker", String(20), nullable=False),
    Column("figi", String(20), nullable=False),
    Column("status", String(20), nullable=False, server_default=text("'proposed'")),
    Column("source", String(20), nullable=False),
    Column("council_run_id", UUID(as_uuid=True)),
    Column("proposed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("entry_suggested", Numeric),
    Column("qty_suggested", Numeric),
    Column("entry_actual", Numeric),
    Column("qty_actual", Numeric),
    Column("opened_at", TIMESTAMP(timezone=True)),
    Column("target_price", Numeric, nullable=False),
    Column("exit_price", Numeric, nullable=False),
    Column("exit_note", Text, nullable=False),
    Column("signal_muted_until", TIMESTAMP(timezone=True)),
    Column("closed_at", TIMESTAMP(timezone=True)),
    Column("close_reason", Text),
    Column("exit_actual", Numeric),
    Column("result_pct", Numeric),
)
```

ВНИМАНИЕ: `BIGSERIAL` создаёт sequence `deals_deal_no_seq` только при CREATE TABLE из
schema.sql — ensure_schema исполняет schema.sql, так что server_default с nextval валиден.
В тестах строки создаются только через репозиторий (insert без deal_no → default).

- [ ] **Step 3: conftest TRUNCATE — добавить `deals`**

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db/tables.py tests/conftest.py
git commit -m "feat: deals table"
```

---

### Task 2: Репозиторий db/deals.py

**Files:**
- Create: `src/roaring_kittens/db/deals.py`
- Test: `tests/test_deals_repo.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_deals_repo.py
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.deals import (
    accept_deal, activate_deal, close_deal, create_proposal, decline_deal,
    expire_if_stale, get_deal, has_recent_proposal, list_deals, mute_deal,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def _propose(session, user_id=42, ticker="SBER"):
    return await create_proposal(
        session, user_id=user_id, ticker=ticker, figi="F", source="council",
        council_run_id=None, entry_suggested=Decimal("262"),
        qty_suggested=Decimal("10"), target_price=Decimal("290"),
        exit_price=Decimal("245"), exit_note="отменят дивиденды")


async def test_deal_lifecycle(db_session_factory):
    async with db_session_factory() as session:
        d = await _propose(session)
        assert d.status == "proposed" and d.deal_no >= 1
        assert await has_recent_proposal(session, 42, "SBER", days=7) is True
        assert await has_recent_proposal(session, 42, "GAZP", days=7) is False
        assert await has_recent_proposal(session, 777, "SBER", days=7) is False
        await accept_deal(session, d.id)
        await activate_deal(session, d.id, entry_actual=Decimal("262.3"),
                            qty_actual=Decimal("10"))
        await session.commit()
    async with db_session_factory() as session:
        d2 = await get_deal(session, d.id)
        assert d2.status == "active" and d2.entry_actual == Decimal("262.3")
        active = await list_deals(session, 42, statuses=("active",))
        assert [x.id for x in active] == [d.id]
        await close_deal(session, d.id, exit_actual=Decimal("270"),
                         close_reason="продал по кнопке",
                         result_pct=Decimal("2.9"))
        await session.commit()
    async with db_session_factory() as session:
        d3 = await get_deal(session, d.id)
        assert d3.status == "closed" and d3.result_pct == Decimal("2.9")


async def test_decline_mute_and_expire(db_session_factory):
    async with db_session_factory() as session:
        a = await _propose(session, ticker="GAZP")
        b = await _propose(session, ticker="LKOH")
        await decline_deal(session, a.id)
        until = datetime.now(tz=timezone.utc) + timedelta(days=3)
        await mute_deal(session, b.id, until=until)
        await session.commit()
    async with db_session_factory() as session:
        assert (await get_deal(session, a.id)).status == "declined"
        assert (await get_deal(session, b.id)).signal_muted_until is not None
        # протухание: старше 48ч -> expired, свежий -> нетронут
        stale = await expire_if_stale(session, b.id, ttl_hours=48)
        assert stale is False   # свежее предложение не протухло
        await session.execute(  # состариваем руками
            __import__("sqlalchemy").text(
                "UPDATE deals SET proposed_at = now() - interval '3 days' "
                "WHERE id = :i"), {"i": str(b.id)})
        assert await expire_if_stale(session, b.id, ttl_hours=48) is True
        assert (await get_deal(session, b.id)).status == "expired"
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/deals.py
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


async def has_recent_proposal(session: AsyncSession, user_id: int, ticker: str,
                              *, days: int = 7) -> bool:
    """Любая сделка по тикеру за окно (кроме declined/expired) глушит новую идею."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    row = (await session.execute(
        select(deals.c.id).where(
            deals.c.user_id == user_id, deals.c.ticker == ticker,
            deals.c.status.notin_(("declined", "expired")),
            deals.c.proposed_at >= since).limit(1))).first()
    return row is not None


async def accept_deal(session: AsyncSession, deal_id: UUIDType) -> None:
    await session.execute(update(deals).where(deals.c.id == deal_id)
                          .values(status="accepted"))


async def decline_deal(session: AsyncSession, deal_id: UUIDType) -> None:
    await session.execute(update(deals).where(deals.c.id == deal_id)
                          .values(status="declined"))


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
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/db/deals.py tests/test_deals_repo.py
git commit -m "feat: deals repository with full lifecycle"
```

---

### Task 3: Лот инструмента (broker + universe)

**Files:**
- Modify: `src/roaring_kittens/broker/tinkoff_client.py` (list_shares), `src/roaring_kittens/universe/universe.py`
- Modify: тесты, где фейкается `list_shares` (найти: `grep -rn "list_shares" tests/`)

- [ ] **Step 1: universe.py — Instrument.lot и разбор тройки**

```python
@dataclass(frozen=True)
class Instrument:
    ticker: str
    figi: str
    name: str
    aliases: frozenset[str] = field(default_factory=frozenset)
    lot: int = 1
```

В `Universe.load`: `shares` теперь `ticker -> (figi, name, lot)`:

```python
            figi, name, lot = shares[t]
            aliases = {name.lower(), t.lower()} | set(EXTRA_ALIASES.get(t, []))
            self._by_ticker[t] = Instrument(t, figi, name, frozenset(aliases), lot)
```

- [ ] **Step 2: tinkoff_client.list_shares — вернуть лот**

В методе, собирающем словарь shares (сейчас `{ticker: (figi, name)}`), добавить
`share.lot` третьим элементом: `{s.ticker: (s.figi, s.name, s.lot)}` (поле `lot`
есть в прото Share Тинькофф SDK). Все фейки list_shares в тестах перевести на
тройку `(figi, name, lot)` c lot=10 для SBER-подобных и lot=1 по умолчанию.

- [ ] **Step 3: Прогнать затронутые тесты локально нельзя — Commit → CI**

```bash
git add src/roaring_kittens/broker/tinkoff_client.py src/roaring_kittens/universe/universe.py tests
git commit -m "feat: instrument lot size from tinkoff shares"
```

---

### Task 4: sizing.py — risk-based размер

**Files:**
- Create: `src/roaring_kittens/sizing.py`
- Test: `tests/test_sizing.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_sizing.py
from decimal import Decimal

from roaring_kittens.sizing import SizedSuggestion, suggest_qty

PV = Decimal("100000")  # портфель 100к


def test_risk_based_qty_basic():
    # риск 1% = 1000₽; стоп-дистанция 262-245=17₽ -> 58.8 акций -> 5 лотов по 10
    s = suggest_qty(portfolio_value=PV, entry=Decimal("262"),
                    exit_price=Decimal("245"), lot=10)
    assert isinstance(s, SizedSuggestion)
    assert s.qty == 50                      # 58 акций -> вниз до целых лотов
    assert s.cost == Decimal("13100")       # 50 × 262
    assert s.risk_rub == Decimal("850")     # 50 × 17
    assert s.over_risk is False


def test_concentration_cap_15pct():
    # стоп близко -> риск-формула даёт огромный размер; кап 15% портфеля
    s = suggest_qty(portfolio_value=PV, entry=Decimal("100"),
                    exit_price=Decimal("99"), lot=1)
    assert s.cost <= PV * Decimal("0.15")
    assert s.qty == 150                     # 15000₽ / 100₽


def test_tiny_portfolio_min_one_lot_flagged():
    # портфель 900₽: 1% = 9₽ риска, лот SBER стоит 2620₽ -> минимум 1 лот, over_risk
    s = suggest_qty(portfolio_value=Decimal("900"), entry=Decimal("262"),
                    exit_price=Decimal("245"), lot=10)
    assert s.qty == 10 and s.over_risk is True


def test_invalid_levels_return_none():
    assert suggest_qty(portfolio_value=PV, entry=Decimal("100"),
                       exit_price=Decimal("100"), lot=1) is None
    assert suggest_qty(portfolio_value=Decimal("0"), entry=Decimal("100"),
                       exit_price=Decimal("90"), lot=1) is None
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/sizing.py
"""Risk-based размер сделки: одна сделка теряет не больше RISK_PCT портфеля.

qty = (RISK_PCT × portfolio) / (entry − exit), вниз до целых лотов;
кап — CONCENTRATION_CAP стоимости портфеля (лимит Risk Manager);
минимум 1 лот (over_risk=True, если 1 лот рискует больше нормы)."""
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

RISK_PCT = Decimal("0.01")            # 1% портфеля на сделку
CONCENTRATION_CAP = Decimal("0.15")   # тот же лимит, что у Risk Manager


@dataclass(frozen=True)
class SizedSuggestion:
    qty: int          # в ШТУКАХ (кратно лоту)
    lots: int
    cost: Decimal     # qty × entry
    risk_rub: Decimal # qty × (entry − exit)
    over_risk: bool   # даже 1 лот рискует больше 1% портфеля


def suggest_qty(*, portfolio_value: Decimal, entry: Decimal,
                exit_price: Decimal, lot: int) -> SizedSuggestion | None:
    per_share_risk = entry - exit_price
    if per_share_risk <= 0 or portfolio_value <= 0 or entry <= 0 or lot < 1:
        return None
    risk_budget = portfolio_value * RISK_PCT
    raw_shares = risk_budget / per_share_risk
    lots = int((raw_shares / lot).to_integral_value(rounding=ROUND_DOWN))
    # кап концентрации
    max_cost = portfolio_value * CONCENTRATION_CAP
    while lots > 0 and lots * lot * entry > max_cost:
        lots -= 1
    over_risk = False
    if lots < 1:
        lots, over_risk = 1, True  # минимум 1 лот, честно флажим риск
    qty = lots * lot
    return SizedSuggestion(qty=qty, lots=lots, cost=qty * entry,
                           risk_rub=qty * per_share_risk, over_risk=over_risk)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/sizing.py tests/test_sizing.py
git commit -m "feat: risk-based deal sizing (1% risk, 15% cap, whole lots)"
```

---

### Task 5: Уровни от PM — Proposal.target_price/exit_price + санити

**Files:**
- Modify: `src/roaring_kittens/committee/schemas.py`, `src/roaring_kittens/committee/manager.py`
- Create: функция `sanitize_levels` в `src/roaring_kittens/deals_service.py` (модуль создаётся здесь)
- Test: `tests/test_deal_levels.py`

- [ ] **Step 1: schemas.py — два поля (не ломают существующие тесты: дефолт None)**

```python
class Proposal(BaseModel):
    action: Literal["buy", "sell", "hold", "wait"]
    stance: Stance
    rationale: str = Field(description="3-5 предложений: решение и почему")
    thesis: str = Field(description="однострочный тезис ставки")
    invalidation: str = Field(description="конкретный триггер, при котором тезис ломается")
    confidence: float = Field(ge=0, le=1)
    target_price: float | None = Field(
        default=None, description="целевая цена фиксации прибыли, ₽ (для buy)")
    exit_price: float | None = Field(
        default=None, description="цена выхода/стопа, ₽ — ниже входа (для buy)")
```

- [ ] **Step 2: manager.py — в system-промпт PM добавить абзац** (в конец существующего):

```
Для action=buy ОБЯЗАТЕЛЬНО заполни target_price (цель фиксации прибыли) и
exit_price (уровень выхода НИЖЕ текущей цены). Отталкивайся от текущей цены,
уровней поддержки/сопротивления из технического блока и своего теза. Числа в ₽.
```

- [ ] **Step 3: Падающий тест санити**

```python
# tests/test_deal_levels.py
from decimal import Decimal

from roaring_kittens.deals_service import sanitize_levels


def test_levels_pass_through_when_sane():
    t, e = sanitize_levels(entry=Decimal("262"), target=290.0, exit_price=245.0)
    assert (t, e) == (Decimal("290"), Decimal("245"))


def test_levels_fallback_when_missing_or_insane():
    # нет уровней -> -7%/+14% от входа
    t, e = sanitize_levels(entry=Decimal("100"), target=None, exit_price=None)
    assert (t, e) == (Decimal("114"), Decimal("93"))
    # exit выше входа — бред -> фолбэк
    t, e = sanitize_levels(entry=Decimal("100"), target=120.0, exit_price=105.0)
    assert e == Decimal("93")
    # exit слишком далеко (>20%) -> фолбэк
    t, e = sanitize_levels(entry=Decimal("100"), target=120.0, exit_price=60.0)
    assert e == Decimal("93")
    # target ниже входа -> фолбэк target, exit валиден остаётся
    t, e = sanitize_levels(entry=Decimal("100"), target=95.0, exit_price=94.0)
    assert t == Decimal("114") and e == Decimal("94")
```

- [ ] **Step 4: Реализовать (начало deals_service.py)**

```python
# src/roaring_kittens/deals_service.py
"""Сделки: уровни, сайзинг-текст, предложение идей, активация/закрытие/конвертация."""
from decimal import ROUND_HALF_UP, Decimal

FALLBACK_EXIT_PCT = Decimal("0.07")    # −7%
FALLBACK_TARGET_PCT = Decimal("0.14")  # +14% (2R)
MIN_EXIT_GAP = Decimal("0.03")         # exit минимум на 3% ниже входа
MAX_EXIT_GAP = Decimal("0.20")         # и максимум на 20%
MIN_TARGET_GAP = Decimal("0.03")


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def sanitize_levels(*, entry: Decimal, target: float | None,
                    exit_price: float | None) -> tuple[Decimal, Decimal]:
    """(target, exit) с фолбэком на детерминированные уровни от входа."""
    fb_target = _q(entry * (1 + FALLBACK_TARGET_PCT))
    fb_exit = _q(entry * (1 - FALLBACK_EXIT_PCT))
    t = Decimal(str(target)) if target else None
    e = Decimal(str(exit_price)) if exit_price else None
    if e is None or not (entry * (1 - MAX_EXIT_GAP) <= e <= entry * (1 - MIN_EXIT_GAP)):
        e = fb_exit
    if t is None or t < entry * (1 + MIN_TARGET_GAP):
        t = fb_target
    return _q(t), _q(e)
```

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/committee/schemas.py src/roaring_kittens/committee/manager.py src/roaring_kittens/deals_service.py tests/test_deal_levels.py
git commit -m "feat: PM price levels with deterministic sanity fallback"
```

---

### Task 6: deals_service — текст идеи + propose

**Files:**
- Modify: `src/roaring_kittens/deals_service.py`
- Test: `tests/test_deal_render.py`

- [ ] **Step 1: Падающий тест рендера**

```python
# tests/test_deal_render.py
from decimal import Decimal

from roaring_kittens.deals_service import build_idea_text
from roaring_kittens.sizing import SizedSuggestion


def test_idea_text_has_levels_size_and_disclaimer():
    s = SizedSuggestion(qty=50, lots=5, cost=Decimal("13100"),
                        risk_rub=Decimal("850"), over_risk=False)
    text = build_idea_text(
        deal_no=12, ticker="SBER", entry=Decimal("262"),
        target=Decimal("290"), exit_price=Decimal("245"),
        exit_note="отменят дивиденды", rationale="Отчёт лучше ожиданий.",
        confidence=0.72, sized=s)
    assert "№12" in text and "SBER" in text and "262" in text
    assert "290" in text and "245" in text
    assert "Продаём если" in text and "отменят дивиденды" in text
    assert "5 лотов (50 шт" in text and "13100" in text
    assert "не является индивидуальной инвестиционной рекомендацией" in text.lower()


def test_idea_text_flags_over_risk_and_no_size():
    s = SizedSuggestion(qty=10, lots=1, cost=Decimal("2620"),
                        risk_rub=Decimal("170"), over_risk=True)
    text = build_idea_text(deal_no=1, ticker="SBER", entry=Decimal("262"),
                           target=Decimal("290"), exit_price=Decimal("245"),
                           exit_note="x", rationale="r", confidence=0.6, sized=s)
    assert "выше нормы" in text          # честная приписка про риск
    text2 = build_idea_text(deal_no=2, ticker="SBER", entry=Decimal("262"),
                            target=Decimal("290"), exit_price=Decimal("245"),
                            exit_note="x", rationale="r", confidence=0.6,
                            sized=None)  # сайзинг не посчитался — без блока размера
    assert "лот" not in text2
```

- [ ] **Step 2: Реализовать build_idea_text + propose_deal_from_council**

```python
# добавить в src/roaring_kittens/deals_service.py
import structlog
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from roaring_kittens.db.deals import create_proposal, has_recent_proposal
from roaring_kittens.sizing import SizedSuggestion, suggest_qty
from roaring_kittens.telegram.formatting import esc
from roaring_kittens.users_service import get_cached_portfolio

log = structlog.get_logger()

DISCLAIMER = "_Не является индивидуальной инвестиционной рекомендацией._"


def build_idea_text(*, deal_no: int, ticker: str, entry: Decimal,
                    target: Decimal, exit_price: Decimal, exit_note: str,
                    rationale: str, confidence: float,
                    sized: SizedSuggestion | None) -> str:
    up = _q((target - entry) / entry * 100)
    dn = _q((entry - exit_price) / entry * 100)
    lines = [
        f"💡 <b>Идея сделки №{deal_no} — купить {ticker} по ~{entry} ₽</b>", "",
        f"Почему: {esc(rationale)}",
        f"Комитет аналитиков: BUY, уверенность {round(confidence * 100)}%.", "",
        f"🎯 Цель: {target} ₽ (+{up}%)",
        f"🛑 Продаём если: цена ниже {exit_price} ₽ (−{dn}%) или {esc(exit_note)}",
    ]
    if sized is not None:
        lines += ["", f"📐 Размер: {sized.lots} лотов ({sized.qty} шт, ~{_q(sized.cost)} ₽)"]
        if sized.over_risk:
            lines.append(f"⚠️ Даже минимальный лот рискует {_q(sized.risk_rub)} ₽ — "
                         f"для твоего портфеля это выше нормы 1%.")
        else:
            lines.append(f"Логика: сработает выход — потеряешь ~{_q(sized.risk_rub)} ₽, "
                         f"это 1% портфеля, который я вижу.")
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def idea_keyboard(deal_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Беру", callback_data=f"deal_take:{deal_id}"),
        InlineKeyboardButton(text="❌ Пропущу", callback_data=f"deal_skip:{deal_id}"),
    ]])


async def propose_deal_from_council(deps, bot, user_id: int, instrument,
                                    outcome) -> None:
    """Approved BUY -> идея сделки. Молчит, если: тикер уже в портфеле юзера,
    была идея за 7 дней, нет цены входа. Ошибки глотает (идея — бонус, не ядро)."""
    try:
        proposal = outcome.proposal
        if not outcome.risk.approved or proposal.action != "buy":
            return
        broker = None
        from roaring_kittens.users_service import get_user_broker
        broker = await get_user_broker(deps, user_id)
        if broker is None:
            return
        snap = await get_cached_portfolio(deps, user_id, broker)
        if snap is None:
            return
        if any(p.ticker == instrument.ticker for p in snap.positions):
            return  # докупки в v1 не предлагаем
        async with deps.session_factory() as session:
            if await has_recent_proposal(session, user_id, instrument.ticker, days=7):
                return
        entry = outcome.state["ctx"].tech.last_close if outcome.state["ctx"].tech else None
        if entry is None:
            return
        target, exit_price = sanitize_levels(
            entry=entry, target=proposal.target_price,
            exit_price=proposal.exit_price)
        sized = suggest_qty(portfolio_value=snap.total_value, entry=entry,
                            exit_price=exit_price, lot=instrument.lot)
        async with deps.session_factory() as session:
            deal = await create_proposal(
                session, user_id=user_id, ticker=instrument.ticker,
                figi=instrument.figi, source="council",
                council_run_id=outcome.run_id, entry_suggested=entry,
                qty_suggested=Decimal(sized.qty) if sized else None,
                target_price=target, exit_price=exit_price,
                exit_note=proposal.invalidation)
            await session.commit()
        await bot.send_message(
            user_id,
            build_idea_text(deal_no=deal.deal_no, ticker=instrument.ticker,
                            entry=entry, target=target, exit_price=exit_price,
                            exit_note=proposal.invalidation,
                            rationale=proposal.thesis,
                            confidence=proposal.confidence, sized=sized),
            reply_markup=idea_keyboard(deal.id))
        log.info("deal_proposed", user=user_id, ticker=instrument.ticker,
                 deal_no=deal.deal_no)
    except Exception as exc:
        log.error("deal_propose_failed", user=user_id,
                  ticker=getattr(instrument, "ticker", "?"), error=str(exc))
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/deals_service.py tests/test_deal_render.py
git commit -m "feat: deal idea rendering and council-to-proposal pipeline"
```

---

### Task 7: /deals + колбэки

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/deals.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/telegram/handlers/start.py` (меню)

- [ ] **Step 1: handlers/deals.py**

```python
# src/roaring_kittens/telegram/handlers/deals.py
"""Сделки: список, принятие/отказ идеи, «продал», «держу дальше»."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from roaring_kittens.db.deals import (
    DealRecord, accept_deal, close_deal, decline_deal, expire_if_stale,
    get_deal, list_deals, mute_deal,
)
from roaring_kittens.db.users import get_active_user
from roaring_kittens.deps import Deps

log = structlog.get_logger()
router = Router()

HOLD_MUTE_DAYS = 3


def _pct(entry: Decimal, now_price: Decimal) -> Decimal:
    return ((now_price - entry) / entry * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def format_deals(open_deals: list[DealRecord], closed: list[DealRecord],
                 prices: dict[str, Decimal]) -> str:
    lines = ["💼 <b>Сделки</b>", ""]
    if open_deals:
        lines.append("📈 <b>Открытые:</b>")
        for d in open_deals:
            entry = d.entry_actual or d.entry_suggested
            now_price = prices.get(d.figi)
            pnl = f" · {'+' if _pct(entry, now_price) >= 0 else ''}{_pct(entry, now_price)}%" \
                if (now_price and entry) else ""
            lines.append(f"№{d.deal_no} {d.ticker} · вход {entry} ₽"
                         f"{f' → сейчас {now_price} ₽' if now_price else ''}{pnl}"
                         f" · цель {d.target_price} / выход {d.exit_price}")
        lines.append("")
    if closed:
        lines.append("📕 <b>Закрытые:</b>")
        total = Decimal("0")
        for d in closed[-10:]:
            res = d.result_pct if d.result_pct is not None else Decimal("0")
            total += res
            days = (d.closed_at - (d.opened_at or d.proposed_at)).days
            mark = "✅" if res >= 0 else "❌"
            lines.append(f"№{d.deal_no} {d.ticker} · "
                         f"{'+' if res >= 0 else ''}{res}% за {days} дн {mark}")
        lines += ["", f"Итог по закрытым: {'+' if total >= 0 else ''}{total}%"]
    if not open_deals and not closed:
        lines.append("Пока пусто. Идеи приходят сами, когда комитет находит "
                     "сделку; свои покупки я тоже подхвачу на утренней сверке.")
    return "\n".join(lines)


@router.message(Command("deals"))
@router.message(F.text == "💼 Сделки")
async def cmd_deals(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        await message.answer("🔒 Сделки доступны подключённым пользователям "
                             "(нужен инвайт-код от владельца).")
        return
    async with deps.session_factory() as session:
        open_deals = await list_deals(session, user.telegram_id,
                                      statuses=("active", "accepted"))
        closed = await list_deals(session, user.telegram_id, statuses=("closed",))
    prices: dict[str, Decimal] = {}
    if open_deals:
        try:
            prices = await deps.broker.get_last_prices(
                [d.figi for d in open_deals])
        except Exception as exc:
            log.warning("deals_prices_failed", error=str(exc))
    await message.answer(format_deals(open_deals, closed, prices))


async def _owned_deal(callback: CallbackQuery, deps: Deps) -> DealRecord | None:
    try:
        deal_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return None
    async with deps.session_factory() as session:
        deal = await get_deal(session, deal_id)
    if deal is None or deal.user_id != callback.from_user.id:
        await callback.answer("Это не твоя сделка", show_alert=True)
        return None
    return deal


@router.callback_query(F.data.startswith("deal_take:"))
async def cb_take(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    async with deps.session_factory() as session:
        if await expire_if_stale(session, deal.id, ttl_hours=48):
            await session.commit()
            await callback.answer("Идея устарела (48ч) — жди следующую",
                                  show_alert=True)
            return
        if deal.status != "proposed":
            await callback.answer("Уже обработана")
            return
        await accept_deal(session, deal.id)
        await session.commit()
    await callback.answer("Записал!")
    await callback.message.answer(
        f"📝 Сделка №{deal.deal_no} {deal.ticker} принята.\n"
        f"Купи в приложении Т-Инвестиций — я увижу покупку на счёте при "
        f"ближайшей сверке и начну следить за целью {deal.target_price} ₽ "
        f"и выходом {deal.exit_price} ₽.")


@router.callback_query(F.data.startswith("deal_skip:"))
async def cb_skip(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    async with deps.session_factory() as session:
        await decline_deal(session, deal.id)
        await session.commit()
    await callback.answer("Ок, пропускаем")


@router.callback_query(F.data.startswith("deal_sold:"))
async def cb_sold(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    if deal.status != "active":
        await callback.answer("Сделка уже закрыта")
        return
    price = None
    try:
        prices = await deps.broker.get_last_prices([deal.figi])
        price = prices.get(deal.figi)
    except Exception as exc:
        log.warning("deal_close_price_failed", error=str(exc))
    entry = deal.entry_actual or deal.entry_suggested
    result = _pct(entry, price) if (price and entry) else None
    async with deps.session_factory() as session:
        await close_deal(session, deal.id, exit_actual=price,
                         close_reason="продал (кнопка)", result_pct=result)
        await session.commit()
    await callback.answer()
    res_txt = f" Результат: {'+' if result >= 0 else ''}{result}%." if result is not None else ""
    await callback.message.answer(
        f"📕 Сделка №{deal.deal_no} {deal.ticker} закрыта.{res_txt} /deals — все.")


@router.callback_query(F.data.startswith("deal_hold:"))
async def cb_hold(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    until = datetime.now(tz=timezone.utc) + timedelta(days=HOLD_MUTE_DAYS)
    async with deps.session_factory() as session:
        await mute_deal(session, deal.id, until=until)
        await session.commit()
    await callback.answer(f"Ок, молчу про №{deal.deal_no} {HOLD_MUTE_DAYS} дня")
```

- [ ] **Step 2: __init__.py — `deals` в импорт и `all_routers.include_router(deals.router)`; start.py — меню**

```python
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Портфель"), KeyboardButton(text="💼 Сделки")],
        [KeyboardButton(text="📅 Дайджест"), KeyboardButton(text="💡 Спросить")],
        [KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)
```

В HELP_TEXT добавить строку: `• <code>/deals</code> — твои сделки: открытые с уровнями, закрытые с результатом`.

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/telegram
git commit -m "feat: /deals command and deal lifecycle callbacks"
```

---

### Task 8: Хуки идей — три пути комитета

**Files:**
- Modify: `src/roaring_kittens/telegram/handlers/council.py`, `src/roaring_kittens/scheduler.py`

- [ ] **Step 1: council.py::cmd_council — после отправки вердикта** (в самом конце функции):

```python
    from roaring_kittens.deals_service import propose_deal_from_council
    await propose_deal_from_council(deps, message.bot, uid, instrument, outcome)
```

- [ ] **Step 2: scheduler.py — те же строки в двух авто-путях:**

В `_validate_one_thesis` после отправки вердикта комитета (последний send_alert):

```python
    from roaring_kittens.deals_service import propose_deal_from_council
    await propose_deal_from_council(deps, bot, owner_id, instrument, outcome)
```

В `_react_for_user` после отправки вердикта комитета (последний send_alert):

```python
    from roaring_kittens.deals_service import propose_deal_from_council
    await propose_deal_from_council(deps, bot, uid, instrument, outcome)
```

(обе — внутри уже существующих budget/use_user контекстов не нуждаются: LLM не зовётся;
propose сам глотает свои ошибки.)

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/telegram/handlers/council.py src/roaring_kittens/scheduler.py
git commit -m "feat: deal ideas from all three council paths"
```

---

### Task 9: positions_sync — активация, закрытие, конвертация

**Files:**
- Modify: `src/roaring_kittens/positions_sync.py`, `src/roaring_kittens/deals_service.py`

- [ ] **Step 1: deals_service — три функции сверки**

```python
# добавить в src/roaring_kittens/deals_service.py
from roaring_kittens.db.deals import (
    activate_deal, close_deal, create_proposal, list_deals,
)


async def sync_deals_for_user(deps, bot, user_id: int, snap) -> None:
    """Утренняя сверка сделок со счётом: активировать accepted, закрыть
    исчезнувшие active, конвертировать «ничейные» позиции. Ошибки — в лог."""
    held = {p.ticker: p for p in snap.positions}
    async with deps.session_factory() as session:
        accepted = await list_deals(session, user_id, statuses=("accepted",))
        active = await list_deals(session, user_id, statuses=("active",))
    covered = {d.ticker for d in accepted} | {d.ticker for d in active}

    for d in accepted:  # покупка появилась на счёте -> active
        pos = held.get(d.ticker)
        if pos is None:
            continue
        async with deps.session_factory() as session:
            await activate_deal(session, d.id, entry_actual=pos.avg_price,
                                qty_actual=pos.quantity)
            await session.commit()
        await bot.send_message(
            user_id,
            f"✅ Вижу покупку: {d.ticker} {pos.quantity} шт по {pos.avg_price} ₽.\n"
            f"Сделка №{d.deal_no} открыта — слежу за целью {d.target_price} ₽ "
            f"и выходом {d.exit_price} ₽.")

    for d in active:  # позиция исчезла -> закрываем по last price
        if d.ticker in held:
            continue
        price = None
        try:
            prices = await deps.broker.get_last_prices([d.figi])
            price = prices.get(d.figi)
        except Exception as exc:
            log.warning("deal_autoclose_price_failed", error=str(exc))
        entry = d.entry_actual or d.entry_suggested
        result = None
        if price and entry:
            result = ((price - entry) / entry * 100).quantize(Decimal("0.1"))
        async with deps.session_factory() as session:
            await close_deal(session, d.id, exit_actual=price,
                             close_reason="позиция закрыта на счёте",
                             result_pct=result)
            await session.commit()
        res_txt = f" Результат: {'+' if result >= 0 else ''}{result}%." \
            if result is not None else ""
        await bot.send_message(
            user_id, f"📕 Вижу продажу {d.ticker} — сделка №{d.deal_no} "
                     f"закрыта.{res_txt} /deals — все.")

    for ticker, pos in held.items():  # «ничейная» позиция -> converted-сделка
        if ticker in covered:
            continue
        target, exit_price = sanitize_levels(entry=pos.current_price,
                                             target=None, exit_price=None)
        async with deps.session_factory() as session:
            deal = await create_proposal(
                session, user_id=user_id, ticker=ticker, figi=pos.figi,
                source="converted", council_run_id=None,
                entry_suggested=pos.avg_price, qty_suggested=pos.quantity,
                target_price=target, exit_price=exit_price,
                exit_note="существенное ухудшение новостного фона",
                status="proposed")
            await activate_deal(session, deal.id, entry_actual=pos.avg_price,
                                qty_actual=pos.quantity)
            await session.commit()
        await bot.send_message(
            user_id,
            f"💼 Взял позицию {ticker} под сопровождение как сделку "
            f"№{deal.deal_no} (вход {pos.avg_price} ₽ со счёта).\n"
            f"🎯 Цель: {target} ₽ · 🛑 Продаём если: ниже {exit_price} ₽.\n"
            f"/deals — все сделки.")
```

- [ ] **Step 2: positions_sync._sync_user — вызвать сверку сделок ПЕРЕД тезисной логикой**

Сразу после получения `snap` (и проверки на None):

```python
    from roaring_kittens.deals_service import sync_deals_for_user
    try:
        await sync_deals_for_user(deps, bot, user_id, snap)
    except Exception as exc:
        log.error("deals_sync_failed", user=user_id, error=str(exc))
```

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/deals_service.py src/roaring_kittens/positions_sync.py
git commit -m "feat: deal activation, auto-close and position conversion at daily sync"
```

---

### Task 10: price_watch — сигналы по уровням сделок

**Files:**
- Modify: `src/roaring_kittens/price_watch.py`
- Test: `tests/test_price_watch.py` (дедупер сигналов)

- [ ] **Step 1: Падающий тест (расширить существующий файл)**

```python
def test_deal_signal_deduper_per_kind():
    from roaring_kittens.price_watch import DealSignalDeduper
    d = DealSignalDeduper()
    today = date(2026, 7, 30)
    assert d.seen("id1", "exit", today) is False
    d.mark("id1", "exit", today)
    assert d.seen("id1", "exit", today) is True
    assert d.seen("id1", "target", today) is False   # другой тип — отдельно
    d.purge(date(2026, 7, 31))
    assert d.seen("id1", "exit", today) is False
```

- [ ] **Step 2: Реализовать в price_watch.py**

```python
class DealSignalDeduper:
    """1 сигнал на (сделка, тип) в день; mark ПОСЛЕ успешной отправки."""

    def __init__(self):
        self._seen: set[tuple[date, str, str]] = set()

    def seen(self, deal_id: str, kind: str, today: date) -> bool:
        return (today, deal_id, kind) in self._seen

    def mark(self, deal_id: str, kind: str, today: date) -> None:
        self._seen.add((today, deal_id, kind))

    def purge(self, today: date) -> None:
        self._seen = {k for k in self._seen if k[0] == today}


_deal_deduper = DealSignalDeduper()


async def watch_deal_levels(deps, bot, today: date) -> None:
    """Проверка целей/выходов active-сделок по last prices. Без LLM."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from roaring_kittens.db.deals import list_deals
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    all_deals = []
    for u in users:
        async with deps.session_factory() as session:
            all_deals += await list_deals(session, u.telegram_id,
                                          statuses=("active",))
    if not all_deals:
        return
    try:
        prices = await deps.broker.get_last_prices(
            list({d.figi for d in all_deals}))
    except Exception as exc:
        log.error("deal_levels_prices_failed", error=str(exc))
        return
    now = datetime.now(tz=timezone.utc)
    for d in all_deals:
        price = prices.get(d.figi)
        if price is None:
            continue
        if d.signal_muted_until and d.signal_muted_until > now:
            continue
        kind = None
        if price <= d.exit_price:
            kind = "exit"
        elif price >= d.target_price:
            kind = "target"
        if kind is None or _deal_deduper.seen(str(d.id), kind, today):
            continue
        entry = d.entry_actual or d.entry_suggested
        pnl = ""
        if entry:
            p = ((price - entry) / entry * 100).quantize(Decimal("0.1"))
            pnl = f" Сейчас: {'+' if p >= 0 else ''}{p}%."
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Продал", callback_data=f"deal_sold:{d.id}"),
            InlineKeyboardButton(text="Держу дальше",
                                 callback_data=f"deal_hold:{d.id}"),
        ]])
        text = (f"🛑 Сделка №{d.deal_no} {d.ticker}: цена {price} ₽ — сработал "
                f"сигнал выхода (ниже {d.exit_price} ₽). Рекомендую продать.{pnl}"
                if kind == "exit" else
                f"🎯 Сделка №{d.deal_no} {d.ticker}: цена {price} ₽ достигла цели "
                f"{d.target_price} ₽. Можно фиксировать прибыль.{pnl}")
        try:
            await send_alert(deps, bot, d.user_id, text,
                             critical=(kind == "exit"), keyboard=kb)
            _deal_deduper.mark(str(d.id), kind, today)
        except Exception as exc:
            log.error("deal_signal_failed", deal=str(d.id), error=str(exc))
```

В `price_watch_job` — вызов в конце (после цикла по интересам):

```python
    try:
        await watch_deal_levels(deps, bot, today)
    except Exception as exc:
        log.error("watch_deal_levels_failed", error=str(exc))
```

и в `_purge_stale_cache` добавить `_deal_deduper.purge(today)`.

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/price_watch.py tests/test_price_watch.py
git commit -m "feat: target/exit level signals for active deals"
```

---

### Task 11: Дайджест — секция «Твои сделки»

**Files:**
- Modify: `src/roaring_kittens/digest/morning.py`

- [ ] **Step 1: В run_morning_digest после построения text** (перед spotlight-блоком):

```python
    from roaring_kittens.db.deals import list_deals
    async with deps.session_factory() as session:
        open_deals = await list_deals(session, chat_id, statuses=("active",))
    if open_deals:
        deal_lines = ["", "💼 <b>Твои сделки:</b>"]
        for d in open_deals:
            entry = d.entry_actual or d.entry_suggested
            pos = next((p for p in snap.positions if p.ticker == d.ticker), None)
            now_p = pos.current_price if pos else None
            pnl = ""
            if now_p and entry:
                p = ((now_p - entry) / entry * 100).quantize(Decimal("0.1"))
                pnl = f" · {'+' if p >= 0 else ''}{p}%"
            deal_lines.append(f"№{d.deal_no} {d.ticker} · вход {entry}"
                              f"{f' → {now_p}' if now_p else ''} ₽{pnl}"
                              f" · цель {d.target_price} / выход {d.exit_price}")
        text += "\n" + "\n".join(deal_lines)
```

(импорт `Decimal` в morning.py уже есть через broker.models? — проверить, при
отсутствии добавить `from decimal import Decimal`.)

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/digest/morning.py
git commit -m "feat: open deals section in morning digest"
```

---

### Task 12: Терминология + новости (Интерфакс / Смартлаб → crowd-only)

**Files:**
- Modify: `src/roaring_kittens/news/sources.py`, `src/roaring_kittens/committee/context.py`, `src/roaring_kittens/scheduler.py`, `src/roaring_kittens/digest/morning.py`, `src/roaring_kittens/telegram/handlers/thesis.py`, `src/roaring_kittens/positions_sync.py`, `src/roaring_kittens/committee/render.py`

- [ ] **Step 1: sources.py**

```python
"""Pluggable список RSS-источников. Добавить источник = добавить строку."""

SOURCES: list[tuple[str, str]] = [  # (source_id, url)
    ("rbc", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("interfax", "https://www.interfax.ru/rss.asp"),
    ("smartlab", "https://smart-lab.ru/rss/"),
]

# Crowd-источники: мнения толпы. Их читает ТОЛЬКО сентимент-аналитик комитета;
# в дайджест, алерты и проверку сделок/тезисов они не попадают.
CROWD_SOURCES: frozenset[str] = frozenset({"smartlab"})
```

- [ ] **Step 2: context.py — заменить локальную константу**

`CROWD_SOURCES = {"smartlab"}` удалить, импортировать:
`from roaring_kittens.news.sources import CROWD_SOURCES`.

- [ ] **Step 3: scheduler.py::poll_news — факты без crowd**

После сбора `fresh_items` (перед validate/impact):

```python
        from roaring_kittens.news.sources import CROWD_SOURCES
        fact_items = [i for i in fresh_items if i.source not in CROWD_SOURCES]
```

и передавать `fact_items` в `validate_theses(...)` и `impact_scan(...)`
(сохранение в БД — по-прежнему все items: сентименту комитета нужны).

- [ ] **Step 4: digest/morning.py — фильтр в run_morning_digest**

После `all_news = await get_news_for_tickers(...)`:

```python
        from roaring_kittens.news.sources import CROWD_SOURCES
        all_news = [n for n in all_news if n.source not in CROWD_SOURCES]
```

- [ ] **Step 5: Терминология «Продаём если» — три места:**

- `thesis.py::format_theses`: `f"🚨 Инвалидация: {esc(t.invalidation)}"` →
  `f"🛑 Продаём если: {esc(t.invalidation)}"`
- `positions_sync.py` (сообщение о новом авто-тезисе):
  `f"🚨 Инвалидация: {esc(draft.invalidation)}"` → `f"🛑 Продаём если: {esc(draft.invalidation)}"`
- `committee/render.py`: найти строку с «Инвалидация» в format_council_verdict
  (`grep -n "Инвалидация" src/`) и заменить на «🛑 Продаём если».
- `thesis.py::cb_thesis_save` ответ: `f"🚨 {esc(proposal['invalidation'])}"` →
  `f"🛑 Продаём если: {esc(proposal['invalidation'])}"`

- [ ] **Step 6: Push → CI, Commit**

```bash
git add src/roaring_kittens/news/sources.py src/roaring_kittens/committee src/roaring_kittens/scheduler.py src/roaring_kittens/digest/morning.py src/roaring_kittens/telegram/handlers/thesis.py src/roaring_kittens/positions_sync.py
git commit -m "feat: interfax news source, smartlab crowd-only, retail-friendly wording"
```

---

### Task 13: README, деплой, E2E, тег

- [ ] **Step 1: README — раздел «Сделки (Phase 5)» + обновить шапку «Сейчас»**

```markdown
## Сделки (Phase 5)

Комитет находит BUY → бот присылает идею: вход, 🎯 цель, 🛑 «продаём если»,
📐 размер (риск 1% портфеля, кап 15%, целые лоты) и кнопки [Беру]/[Пропущу].
Принял → купил в Т-Инвестициях → бот сам видит покупку на счёте (read-only токен),
открывает сделку №N и следит за уровнями (price_watch, без LLM). Сигналы
🛑 выход / 🎯 цель с кнопками [Продал]/[Держу дальше]. Продажу со счёта бот тоже
видит и закрывает сделку с результатом. Существующие и самостоятельные покупки
конвертируются в сделки на утренней сверке. /deals — открытые с уровнями,
закрытые с результатом. Новости: Интерфакс+РБК — факты, Смартлаб — только
сентимент комитета. Каждая идея: «не является ИИР».
```

- [ ] **Step 2: Deploy** — `railway up --service app --ci`; в логах ждать
`bot_starting`, затем `news_polled source=interfax` (fetched>0 — фид жив; при
ошибках фида — откатить строку interfax и задеплоить снова).

- [ ] **Step 3: MANUAL — E2E-чеклист**

- [ ] Утренняя сверка конвертировала SBER и VTBR в сделки №1/№2 (сообщения + /deals)
- [ ] /council по тикеру НЕ из портфеля с approved BUY → пришла идея с размером и кнопками
- [ ] [Беру] → инструкция; купить 1 лот руками → после сверки «✅ Вижу покупку»
- [ ] /deals показывает открытые с «сейчас» и уровнями
- [ ] Дайджест содержит секцию «💼 Твои сделки»
- [ ] [Продал] или продажа руками → «📕 закрыта» с результатом
- [ ] В дайджесте больше нет постов Смартлаба; в логах interfax отдаёт новости
- [ ] Нигде в сообщениях не осталось слова «Инвалидация»

- [ ] **Step 4: Тег**

```bash
git tag phase-5 && git push origin phase-5
```

---

## Self-review checklist (выполнен при написании)

- **Требования юзера:** идеи сделок с кнопками ✅ (T6-T8) · авто-детект покупки ✅ (T9) · сигнал закрытия ✅ (T10) · понятный список открытых/закрытых ✅ (T7) · «инвалидация» → понятное слово ✅ (T12) · Интерфакс вместо Смартлаба в фактах ✅ (T12) · реалистичная частота ✅ (guard 7д, только approved BUY) · risk-based размер ✅ (T4) · конвертация текущих позиций ✅ (T9)
- **Типы согласованы:** DealRecord/create_proposal/list_deals (T2) в T6/T7/T9/T10/T11; SizedSuggestion/suggest_qty (T4) в T6; sanitize_levels (T5) в T6/T9; Instrument.lot (T3) в T6; propose_deal_from_council (T6) в T8; колбэки deal_sold/deal_hold (T7) рендерятся в T10
- **Прод-инварианты:** mark/mute ПОСЛЕ успешной отправки (T10), per-deal try/except в сверке и сигналах, esc() на LLM-текстах идей, идеи не зовут LLM повторно (уровни из уже оплаченного вердикта)
- **Бюджет:** новых LLM-вызовов НЕТ (уровни — поля существующего PM-вызова; мониторинг — арифметика)
