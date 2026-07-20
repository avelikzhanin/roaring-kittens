# Phase 4a «Реактивность» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот реагирует на события за минуты, а не раз в полчаса: опрос новостей каждые 5 минут, Impact Classifier (gpt-4o-mini) для тикеров портфеля и watchlist, HIGH/critical → алерт + авто-комитет, тихие часы 22:00–08:00 с ночным буфером (critical — сквозь), троттлинг ≤3/час, `/watch`-список и дневной прайс-алерт |движение|≥5%.

**Architecture:** Единый роутер уведомлений `send_alert` (quiet-hours → буфер в БД, троттлинг in-memory, critical — сквозь всё) — через него идут и валидатор тезисов, и новый impact-скан, и прайс-алерты; ночной буфер дренится перед утренним дайджестом. Тезисные тикеры остаются за validate_theses (он возвращает обработанный set), impact_scan берёт остальные из портфеля∪watchlist. Мультитенантность — отдельный план 4b; схема watchlists уже с `owner_id` (готова к 4b).

**Tech Stack:** существующий, новых зависимостей НЕТ (zoneinfo — stdlib).

**Spec:** §7 (триггеры, Impact Classifier), §9 (quiet hours, троттлинг, critical override).

**Verification model:** тесты в GitHub Actions CI; батчи → push → `gh run watch`; деплой `railway up --service app --ci`.

**Сознательные решения:**
1. **Ночью авто-комитет не гоняем** для HIGH (алерт буферится, юзер утром решит) — LLM-деньги ночью не жжём; **critical (делистинг/санкции на компанию/слом тезиса) — сквозь всё**, включая комитет.
2. Троттлинг-переполнение уходит в тот же ночной буфер (придёт с утренним дайджестом) — «слабые группируются» из спеки.
3. Прайс-алерт v1 — автоматический дневной |move|≥5% (без ручных уровней /alert — YAGNI, уровни есть в инвалидациях тезисов).
4. Буфер хранит только текст: кнопки при буферизации теряются (утром юзер запустит /council сам).
5. Кэш prev_close и дедуп прайс-алертов — in-memory (сброс при рестарте допустим).

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── alerts.py               # NEW: is_quiet_hours, AlertThrottle, send_alert
├── price_watch.py          # NEW: significant_move + дневной джоб
├── committee/impact.py     # NEW: ImpactCheck + run_impact_check + decide_impact_action
├── db/
│   ├── watchlist.py        # NEW
│   ├── alerts_buffer.py    # NEW
│   └── tables.py           # MOD: watchlists, alert_buffer
├── broker/tinkoff_client.py# MOD: + get_last_prices (pure map_last_prices)
├── scheduler.py            # MOD: 5-мин опрос; validate_theses→send_alert+set; impact_scan; price-cron
├── digest/morning.py       # без изменений (дренаж в scheduler.morning_digest_job)
├── deps.py                 # MOD: + alert_throttle
└── telegram/handlers/
    ├── watchlist.py        # NEW: /watch /unwatch /watchlist
    ├── start.py            # MOD: HELP
    └── __init__.py         # MOD
db/schema.sql               # MOD: 2 таблицы
tests/: test_alerts.py, test_impact.py, test_watchlist_repo.py, test_alerts_buffer.py,
        test_price_watch.py, test_last_prices.py, test_watchlist_render.py
```

---

### Task 1: Схема — watchlists и alert_buffer

**Files:**
- Modify: `db/schema.sql`, `src/roaring_kittens/db/tables.py`, `tests/conftest.py`

- [ ] **Step 1: schema.sql (перед bot_state)**

```sql
CREATE TABLE IF NOT EXISTS watchlists (
    owner_id BIGINT NOT NULL,
    ticker   VARCHAR(20) NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, ticker)
);

CREATE TABLE IF NOT EXISTS alert_buffer (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    chat_id    BIGINT NOT NULL,
    payload    TEXT NOT NULL
);
```

- [ ] **Step 2: tables.py (перед bot_state)**

```python
watchlists = Table(
    "watchlists", metadata,
    Column("owner_id", BigInteger, primary_key=True),
    Column("ticker", String(20), primary_key=True),
    Column("added_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

alert_buffer = Table(
    "alert_buffer", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("chat_id", BigInteger, nullable=False),
    Column("payload", Text, nullable=False),
)
```

- [ ] **Step 3: conftest TRUNCATE — добавить `watchlists, alert_buffer`**

```python
    await conn.execute(
        "TRUNCATE news_events, usage_log, bot_state, council_runs, call_scores, "
        "calls, theses, insights, watchlists, alert_buffer")
```

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db/tables.py tests/conftest.py
git commit -m "feat: watchlists and alert_buffer tables"
```

---

### Task 2: Репозитории watchlist и буфера

**Files:**
- Create: `src/roaring_kittens/db/watchlist.py`, `src/roaring_kittens/db/alerts_buffer.py`
- Test: `tests/test_watchlist_repo.py`, `tests/test_alerts_buffer.py`

- [ ] **Step 1: Падающие тесты**

```python
# tests/test_watchlist_repo.py
import os

import pytest

from roaring_kittens.db.watchlist import add_to_watchlist, list_watchlist, remove_from_watchlist

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
```

```python
# tests/test_alerts_buffer.py
import os

import pytest

from roaring_kittens.db.alerts_buffer import drain_alerts, push_alert

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_push_and_drain_clears(db_session_factory):
    async with db_session_factory() as session:
        await push_alert(session, 42, "первый")
        await push_alert(session, 42, "второй")
        await push_alert(session, 777, "чужой")
        await session.commit()
    async with db_session_factory() as session:
        drained = await drain_alerts(session, 42)
        await session.commit()
        assert drained == ["первый", "второй"]  # по created_at
    async with db_session_factory() as session:
        assert await drain_alerts(session, 42) == []       # опустошён
        assert await drain_alerts(session, 777) == ["чужой"]  # чужие не тронуты
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/watchlist.py
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import watchlists


async def add_to_watchlist(session: AsyncSession, owner_id: int, ticker: str) -> bool:
    stmt = insert(watchlists).values(owner_id=owner_id, ticker=ticker) \
        .on_conflict_do_nothing(index_elements=["owner_id", "ticker"])
    result = await session.execute(stmt)
    return bool(result.rowcount)


async def remove_from_watchlist(session: AsyncSession, owner_id: int, ticker: str) -> bool:
    result = await session.execute(
        delete(watchlists).where(watchlists.c.owner_id == owner_id,
                                 watchlists.c.ticker == ticker))
    return bool(result.rowcount)


async def list_watchlist(session: AsyncSession, owner_id: int) -> list[str]:
    rows = (await session.execute(
        select(watchlists.c.ticker).where(watchlists.c.owner_id == owner_id)
        .order_by(watchlists.c.ticker))).fetchall()
    return [r[0] for r in rows]
```

```python
# src/roaring_kittens/db/alerts_buffer.py
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import alert_buffer


async def push_alert(session: AsyncSession, chat_id: int, payload: str) -> None:
    await session.execute(alert_buffer.insert().values(chat_id=chat_id, payload=payload))


async def drain_alerts(session: AsyncSession, chat_id: int) -> list[str]:
    rows = (await session.execute(
        select(alert_buffer.c.id, alert_buffer.c.payload)
        .where(alert_buffer.c.chat_id == chat_id)
        .order_by(alert_buffer.c.created_at))).fetchall()
    if rows:
        await session.execute(
            delete(alert_buffer).where(alert_buffer.c.id.in_([r[0] for r in rows])))
    return [r[1] for r in rows]
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/db/watchlist.py src/roaring_kittens/db/alerts_buffer.py tests/test_watchlist_repo.py tests/test_alerts_buffer.py
git commit -m "feat: watchlist and alert-buffer repositories"
```

---

### Task 3: alerts.py — quiet hours, троттлинг, единый роутер

**Files:**
- Create: `src/roaring_kittens/alerts.py`
- Modify: `src/roaring_kittens/deps.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_alerts.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import roaring_kittens.alerts as alerts_mod
from roaring_kittens.alerts import AlertThrottle, is_quiet_hours, send_alert

MSK = ZoneInfo("Europe/Moscow")


def _msk(h, m=0):
    return datetime(2026, 7, 18, h, m, tzinfo=MSK)


def test_quiet_hours_boundaries():
    assert is_quiet_hours(_msk(21, 59)) is False
    assert is_quiet_hours(_msk(22, 0)) is True
    assert is_quiet_hours(_msk(3)) is True
    assert is_quiet_hours(_msk(7, 59)) is True
    assert is_quiet_hours(_msk(8, 0)) is False
    assert is_quiet_hours(_msk(12)) is False


def test_throttle_three_per_hour_sliding():
    t = AlertThrottle(max_per_hour=3)
    base = _msk(12)
    assert t.allow(base) and t.allow(base) and t.allow(base)
    assert t.allow(base + timedelta(minutes=10)) is False       # 4-й в окне
    assert t.allow(base + timedelta(minutes=61)) is True        # окно уехало


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


def _deps(now_msk):
    return SimpleNamespace(
        settings=SimpleNamespace(tz="Europe/Moscow"),
        session_factory=lambda: FakeSession(),
        alert_throttle=AlertThrottle(max_per_hour=3),
        _now=now_msk,  # для подмены времени в тесте
    )


async def test_send_alert_routing(monkeypatch):
    pushed = []

    async def fake_push(session, chat_id, payload):
        pushed.append(payload)

    monkeypatch.setattr(alerts_mod, "push_alert", fake_push)
    bot = SimpleNamespace(send_message=AsyncMock())

    day = _deps(_msk(12))
    monkeypatch.setattr(alerts_mod, "_now_local", lambda deps: day._now)
    # днём — шлётся
    assert await send_alert(day, bot, 42, "текст") == "sent"
    bot.send_message.assert_awaited_once()
    # 3/час: 2-й и 3-й ок, 4-й — в буфер
    assert await send_alert(day, bot, 42, "т2") == "sent"
    assert await send_alert(day, bot, 42, "т3") == "sent"
    assert await send_alert(day, bot, 42, "т4") == "buffered"
    assert pushed == ["т4"]
    # ночь: буферится, critical — сквозь
    night = _deps(_msk(23))
    monkeypatch.setattr(alerts_mod, "_now_local", lambda deps: night._now)
    assert await send_alert(night, bot, 42, "ночной") == "buffered"
    assert await send_alert(night, bot, 42, "critical!", critical=True) == "sent"
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/alerts.py
"""Единый роутер алертов: quiet hours 22:00-08:00 МСК -> ночной буфер,
троттлинг <=3/час -> буфер, critical -> сквозь всё."""
from collections import deque
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog

from roaring_kittens.db.alerts_buffer import push_alert

log = structlog.get_logger()

QUIET_START = time(22, 0)
QUIET_END = time(8, 0)


def is_quiet_hours(now_local: datetime) -> bool:
    t = now_local.time()
    return t >= QUIET_START or t < QUIET_END


class AlertThrottle:
    """In-memory скользящее окно: не больше max_per_hour несрочных алертов."""

    def __init__(self, max_per_hour: int = 3):
        self.max_per_hour = max_per_hour
        self._sent: deque[datetime] = deque()

    def allow(self, now: datetime) -> bool:
        hour_ago = now - timedelta(hours=1)
        while self._sent and self._sent[0] <= hour_ago:
            self._sent.popleft()
        if len(self._sent) >= self.max_per_hour:
            return False
        self._sent.append(now)
        return True


def _now_local(deps) -> datetime:
    return datetime.now(tz=ZoneInfo(deps.settings.tz))


async def send_alert(deps, bot, chat_id: int, text: str, *,
                     critical: bool = False, keyboard=None) -> str:
    """Возвращает 'sent' | 'buffered'. Буферизованные приходят с утренним дайджестом
    (кнопки при буферизации теряются — сохраняется только текст)."""
    now = _now_local(deps)
    if not critical:
        if is_quiet_hours(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_quiet", chat_id=chat_id)
            return "buffered"
        if not deps.alert_throttle.allow(now):
            async with deps.session_factory() as session:
                await push_alert(session, chat_id, text)
                await session.commit()
            log.info("alert_buffered_throttle", chat_id=chat_id)
            return "buffered"
    await bot.send_message(chat_id, text, reply_markup=keyboard)
    return "sent"
```

`deps.py` — добавить поле (рядом с ask_limiter, импорт из alerts создаёт цикл? alerts.py не импортирует deps — ок):

```python
from roaring_kittens.alerts import AlertThrottle
# в @dataclass Deps:
    alert_throttle: AlertThrottle = field(default_factory=AlertThrottle)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/alerts.py src/roaring_kittens/deps.py tests/test_alerts.py
git commit -m "feat: alert router with quiet hours, throttle and night buffer"
```

---

### Task 4: broker.get_last_prices

**Files:**
- Modify: `src/roaring_kittens/broker/tinkoff_client.py`
- Test: `tests/test_last_prices.py`

- [ ] **Step 1: Падающий тест (pure map)**

```python
# tests/test_last_prices.py
from decimal import Decimal
from types import SimpleNamespace

from tinkoff.invest import Quotation

from roaring_kittens.broker.tinkoff_client import map_last_prices


def test_map_last_prices():
    resp = SimpleNamespace(last_prices=[
        SimpleNamespace(figi="F1", price=Quotation(units=283, nano=900000000)),
        SimpleNamespace(figi="F2", price=Quotation(units=60, nano=875000000)),
    ])
    prices = map_last_prices(resp)
    assert prices == {"F1": Decimal("283.9"), "F2": Decimal("60.875")}
```

- [ ] **Step 2: Реализовать (в tinkoff_client.py)**

```python
def map_last_prices(resp) -> dict[str, Decimal]:
    """Чистая функция: ответ get_last_prices -> figi->цена."""
    return {p.figi: quotation_to_decimal(p.price) for p in resp.last_prices}
```

и метод в TinkoffBroker (после get_dividends):

```python
    @retry_async(attempts=3, base_delay=1.0)
    async def get_last_prices(self, figis: list[str]) -> dict[str, Decimal]:
        if not figis:
            return {}
        async with AsyncClient(self._token) as client:
            resp = await client.market_data.get_last_prices(figi=figis)
            return map_last_prices(resp)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/broker/tinkoff_client.py tests/test_last_prices.py
git commit -m "feat: broker last prices for intraday move alerts"
```

---

### Task 5: Impact Classifier

**Files:**
- Create: `src/roaring_kittens/committee/impact.py`
- Test: `tests/test_impact.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_impact.py
from datetime import datetime, timezone

from roaring_kittens.committee.impact import (
    ImpactCheck, decide_impact_action, run_impact_check,
)
from roaring_kittens.news.models import NewsItem


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_impact_check_uses_mini():
    llm = FakeLLM(ImpactCheck(impact="high", direction="bearish",
                              reasoning_short="дивы ниже консенсуса"))
    news = [NewsItem(source="rbc", url="https://x/1",
                     headline="ВТБ рекомендовал дивиденды ниже ожиданий", body=None,
                     published_at=datetime.now(tz=timezone.utc), tickers=["VTBR"])]
    check = await run_impact_check(llm, "VTBR", news)
    assert check.impact == "high"
    assert llm.calls == [("impact_check", "gpt-4o-mini")]


def test_decide_impact_action_matrix():
    assert decide_impact_action("critical", council_recent=True) == "council_critical"
    assert decide_impact_action("critical", council_recent=False) == "council_critical"
    assert decide_impact_action("high", council_recent=False) == "council"
    assert decide_impact_action("high", council_recent=True) == "notify"
    assert decide_impact_action("medium", council_recent=False) == "notify"
    assert decide_impact_action("low", council_recent=False) == "nothing"
    assert decide_impact_action("noise", council_recent=False) == "nothing"
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/impact.py
"""Классификатор значимости свежих новостей для тикеров без тезиса (портфель/watchlist)."""
from typing import Literal

from pydantic import BaseModel, Field

from roaring_kittens.news.models import NewsItem

IMPACT_MODEL = "gpt-4o-mini"

IMPACT_SYSTEM = """Ты оцениваешь значимость свежих новостей для КОНКРЕТНОЙ акции Мосбиржи.
Категории:
- critical: делистинг, санкции ПРЯМО на компанию, арест активов/менеджмента,
  крупная авария/катастрофа на её объектах, доп.эмиссия с размытием.
- high: решение по дивидендам (особенно vs ожиданий), M&A, отчётность сильно
  лучше/хуже консенсуса, штраф/иск на значимую сумму, смена CEO.
- medium: прогнозы аналитиков по бумаге, операционные результаты, новости сектора
  с прямым влиянием.
- low: обычные корпоративные новости без ценового смысла.
- noise: PR, повторы, общерыночные обзоры, упоминания вскользь.
Общерыночный фон (индекс, настроение рынка, санкции «в целом») — noise.
Сомневаешься между уровнями — бери НИЖНИЙ. По-русски, кратко."""


class ImpactCheck(BaseModel):
    impact: Literal["critical", "high", "medium", "low", "noise"]
    direction: Literal["bullish", "bearish", "ambiguous"]
    reasoning_short: str = Field(description="одно предложение почему")


async def run_impact_check(llm, ticker: str, news: list[NewsItem]) -> ImpactCheck:
    headlines = "\n".join(f"- {n.headline}" for n in news[:8])
    user = f"Тикер: {ticker}\n\nСвежие новости:\n{headlines}"
    return await llm.parse(model=IMPACT_MODEL, operation="impact_check",
                           messages=[{"role": "system", "content": IMPACT_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ImpactCheck)


def decide_impact_action(impact: str, council_recent: bool) -> str:
    """critical — комитет сквозь всё; high — комитет с суточным guard'ом; medium — алерт."""
    if impact == "critical":
        return "council_critical"
    if impact == "high":
        return "notify" if council_recent else "council"
    if impact == "medium":
        return "notify"
    return "nothing"
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/impact.py tests/test_impact.py
git commit -m "feat: news impact classifier for portfolio/watchlist tickers"
```

---

### Task 6: validate_theses через send_alert + возврат обработанных тикеров

**Files:**
- Modify: `src/roaring_kittens/scheduler.py`

- [ ] **Step 1: Правки validate_theses**

Сигнатура: `async def validate_theses(deps, bot, fresh_items: list) -> set[str]:` —
возвращает тикеры, которые он взял на себя (для impact_scan). Изменения:
- в начале `handled: set[str] = set()`; после построения `theses_to_check`:
  `handled = {t.ticker for t in theses_to_check}`; все `return` → `return handled`
  (ранние выходы возвращают `set()`).
- Уведомления через роутер (импорт `from roaring_kittens.alerts import send_alert`):
  - ветка notify: `weakened` → `await send_alert(deps, bot, owner_id, text)`;
    `invalidated`-notify (когда комитет недавно был) → `await send_alert(..., critical=True)`.
  - сообщение «🚨 Новости ломают тезис… Собираю комитет…» → `send_alert(..., critical=True)`
  - финальный вердикт авто-комитета → `send_alert(..., critical=True, keyboard=keyboard)`
  (слом тезиса = critical по определению — пробивает ночь и троттлинг).

Конкретно, ветка notify становится:

```python
        if action == "notify":
            text = (f"⚠️ Тезис по <b>{thesis.ticker}</b> "
                    f"{'СЛОМАН' if check.status == 'invalidated' else 'ослаблен'}: "
                    f"{esc(check.reasoning_short)}\nТезис: {esc(thesis.thesis)}")
            if check.status == "weakened":
                last = thesis.last_weakened_at
                if last and datetime.now(tz=timezone.utc) - last < WEAKENED_COOLDOWN:
                    log.info("weakened_suppressed_cooldown", ticker=thesis.ticker)
                    continue
                async with deps.session_factory() as session:
                    await mark_thesis_weakened(session, thesis.id)
                    await session.commit()
                await send_alert(deps, bot, owner_id, text)
            else:
                await send_alert(deps, bot, owner_id, text, critical=True)
            continue
```

а два сообщения council-ветки — `await send_alert(deps, bot, owner_id, ..., critical=True)`
(у вердикта — `keyboard=keyboard`).

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/scheduler.py
git commit -m "feat: thesis validator routes through alert router and reports handled tickers"
```

---

### Task 7: impact_scan + прошивка poll_news (5 минут)

**Files:**
- Modify: `src/roaring_kittens/scheduler.py`

- [ ] **Step 1: impact_scan (после validate_theses в scheduler.py)**

```python
async def impact_scan(deps, bot, fresh_items: list, skip_tickers: set[str]) -> None:
    """HIGH-impact реакция для тикеров портфеля/watchlist БЕЗ тезиса (те — у валидатора)."""
    if not fresh_items:
        return
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    by_ticker: dict[str, list] = {}
    for item in fresh_items:
        if len(item.tickers) > GENERIC_NEWS_TICKER_CAP:
            continue
        for t in item.tickers:
            by_ticker.setdefault(t, []).append(item)
    if not by_ticker:
        return
    try:
        snap = await deps.broker.get_portfolio()
        portfolio = {p.ticker for p in snap.positions}
    except Exception as exc:
        log.warning("impact_portfolio_failed", error=str(exc))
        portfolio = set()
    async with deps.session_factory() as session:
        watched = set(await list_watchlist(session, owner_id))
    interest = (portfolio | watched) - skip_tickers
    for ticker in sorted(set(by_ticker) & interest):
        news = by_ticker[ticker]
        async with deps.session_factory() as session:
            recent = await council_ran_recently(session, ticker, hours=24)
        try:
            check = await run_impact_check(deps.llm, ticker, news)
        except Exception as exc:
            log.error("impact_check_failed", ticker=ticker, error=str(exc))
            continue
        action = decide_impact_action(check.impact, recent)
        if action == "nothing":
            continue
        headline = news[0].headline
        text = (f"⚡️ <b>{check.impact.upper()} — {ticker}</b>\n"
                f"{esc(headline)}\n{esc(check.reasoning_short)}")
        if action == "notify":
            await send_alert(deps, bot, owner_id, text)
            continue
        critical = action == "council_critical"
        status = await send_alert(deps, bot, owner_id, text + "\nСобираю комитет…",
                                  critical=critical)
        if status != "sent":
            continue  # ночью HIGH буферится — комитет не гоняем, утром юзер решит
        instrument = deps.universe.resolve(ticker)
        if instrument is None:
            continue
        try:
            outcome = await run_council_flow(deps, instrument, owner_id)
        except Exception as exc:
            log.error("impact_council_failed", ticker=ticker, error=str(exc))
            continue
        keyboard = None
        if outcome.run_id is not None:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                             callback_data=f"proto:{outcome.run_id}")]]
            if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
                buttons.append([InlineKeyboardButton(
                    text="📌 Принять тезис",
                    callback_data=f"thesis_save:{outcome.run_id}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_alert(deps, bot, owner_id,
                         format_council_verdict(instrument.ticker, outcome.state["views"],
                                                outcome.state["debate"], outcome.proposal,
                                                outcome.risk),
                         critical=critical, keyboard=keyboard)
```

Импорты вверху scheduler.py добавить:

```python
from roaring_kittens.alerts import send_alert
from roaring_kittens.committee.impact import decide_impact_action, run_impact_check
from roaring_kittens.db.watchlist import list_watchlist
```

- [ ] **Step 2: poll_news — вызвать сканы и 5-минутный интервал**

Хвост `poll_news`:

```python
    if bot is not None and fresh_items:
        handled: set[str] = set()
        try:
            handled = await validate_theses(deps, bot, fresh_items)
        except Exception as exc:
            log.error("validate_theses_failed", error=str(exc))
        try:
            await impact_scan(deps, bot, fresh_items, skip_tickers=handled)
        except Exception as exc:
            log.error("impact_scan_failed", error=str(exc))
```

В `build_scheduler`: `poll_news` interval `minutes=30` → `minutes=5`.

- [ ] **Step 3: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/scheduler.py
git commit -m "feat: impact scan with auto-council + 5-minute news polling"
```

---

### Task 8: Дневной прайс-алерт |move| ≥ 5%

**Files:**
- Create: `src/roaring_kittens/price_watch.py`
- Modify: `src/roaring_kittens/scheduler.py`
- Test: `tests/test_price_watch.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_price_watch.py
from datetime import date
from decimal import Decimal

from roaring_kittens.price_watch import DayMoveDeduper, significant_move


def test_significant_move_threshold():
    assert significant_move(Decimal("100"), Decimal("94.9")) == Decimal("-5.1")
    assert significant_move(Decimal("100"), Decimal("105.0")) == Decimal("5.0")
    assert significant_move(Decimal("100"), Decimal("104.9")) is None   # < 5%
    assert significant_move(Decimal("0"), Decimal("100")) is None       # нет базы


def test_deduper_once_per_day():
    d = DayMoveDeduper()
    today, tomorrow = date(2026, 7, 18), date(2026, 7, 19)
    assert d.allow("SBER", today) is True
    assert d.allow("SBER", today) is False
    assert d.allow("GAZP", today) is True
    assert d.allow("SBER", tomorrow) is True  # новый день — можно снова
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/price_watch.py
"""Дневной прайс-алерт: |движение от вчерашнего закрытия| >= 5% — раз в день на тикер."""
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog

from roaring_kittens.alerts import send_alert
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import get_active_theses
from roaring_kittens.db.watchlist import list_watchlist
from roaring_kittens.telegram.formatting import esc

log = structlog.get_logger()

DAY_MOVE_THRESHOLD_PP = Decimal("5")


def significant_move(prev_close: Decimal, last: Decimal) -> Decimal | None:
    if not prev_close:
        return None
    move = ((last - prev_close) / prev_close * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)
    return move if abs(move) >= DAY_MOVE_THRESHOLD_PP else None


class DayMoveDeduper:
    """Один алерт на тикер в день (in-memory, сброс при рестарте допустим)."""

    def __init__(self):
        self._seen: set[tuple[date, str]] = set()

    def allow(self, ticker: str, today: date) -> bool:
        key = (today, ticker)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


_deduper = DayMoveDeduper()
_prev_close_cache: dict[tuple[date, str], Decimal] = {}


async def _prev_close(deps, figi: str, today: date) -> Decimal | None:
    key = (today, figi)
    if key not in _prev_close_cache:
        try:
            candles = await deps.broker.get_daily_candles(figi, days=10)
        except Exception as exc:
            log.warning("price_watch_candles_failed", figi=figi, error=str(exc))
            return None
        done = sorted(candles, key=lambda c: c.day)
        if not done:
            return None
        _prev_close_cache[key] = done[-1].close  # последняя ЗАВЕРШЁННАЯ сессия
    return _prev_close_cache[key]


async def price_watch_job(deps, bot) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    figi_by_ticker: dict[str, str] = {}
    try:
        snap = await deps.broker.get_portfolio()
        for p in snap.positions:
            figi_by_ticker[p.ticker] = p.figi
    except Exception as exc:
        log.warning("price_watch_portfolio_failed", error=str(exc))
    async with deps.session_factory() as session:
        watched = await list_watchlist(session, owner_id)
        theses = await get_active_theses(session)
    for t in watched:
        instr = deps.universe.get(t)
        if instr:
            figi_by_ticker.setdefault(t, instr.figi)
    for th in theses:
        figi_by_ticker.setdefault(th.ticker, th.figi)
    if not figi_by_ticker:
        return
    try:
        prices = await deps.broker.get_last_prices(list(figi_by_ticker.values()))
    except Exception as exc:
        log.error("price_watch_last_prices_failed", error=str(exc))
        return
    today = datetime.now(tz=timezone.utc).date()
    for ticker, figi in figi_by_ticker.items():
        last = prices.get(figi)
        if last is None:
            continue
        prev = await _prev_close(deps, figi, today)
        if prev is None:
            continue
        move = significant_move(prev, last)
        if move is None or not _deduper.allow(ticker, today):
            continue
        arrow = "📈" if move > 0 else "📉"
        await send_alert(
            deps, bot, owner_id,
            f"{arrow} <b>{ticker}</b> {'+' if move > 0 else '−'}{abs(move)}% за день "
            f"({esc(str(prev))} → {esc(str(last))} ₽). Разбор: /council {ticker}")
    log.info("price_watch_done", tickers=len(figi_by_ticker))
```

В `build_scheduler` (торговые часы МСК, каждые 30 мин):

```python
from roaring_kittens.price_watch import price_watch_job

    scheduler.add_job(price_watch_job, "cron", day_of_week="mon-fri",
                      hour="10-18", minute="*/30", args=[deps, bot],
                      id="price_watch", max_instances=1, coalesce=True)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/price_watch.py src/roaring_kittens/scheduler.py tests/test_price_watch.py
git commit -m "feat: intraday 5%-move price alerts for portfolio/watchlist/theses"
```

---

### Task 9: Ночной буфер — выдача перед утренним дайджестом

**Files:**
- Modify: `src/roaring_kittens/scheduler.py` (morning_digest_job)

- [ ] **Step 1: Реализовать**

```python
from roaring_kittens.committee.render import chunk_lines
from roaring_kittens.db.alerts_buffer import drain_alerts

async def morning_digest_job(deps: Deps, bot) -> None:
    """Утренний дайджест шлём владельцу (первый /start). Пока владельца нет — скипаем."""
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        log.warning("digest_skipped_no_owner")
        return
    async with deps.session_factory() as session:
        buffered = await drain_alerts(session, owner_id)
        await session.commit()
    if buffered:
        lines = ["🌙 <b>Ночью накопилось:</b>", ""]
        for item in buffered:
            lines.append(item)
            lines.append("")
        for chunk in chunk_lines(lines):
            await bot.send_message(owner_id, chunk)
    await run_morning_digest(deps, bot, owner_id)
```

(буферизованные тексты уже экранированы на этапе создания — повторно не экранируем)

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/scheduler.py
git commit -m "feat: flush night alert buffer before morning digest"
```

---

### Task 10: /watch /unwatch /watchlist

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/watchlist.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/telegram/handlers/start.py`
- Test: `tests/test_watchlist_render.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_watchlist_render.py
from roaring_kittens.telegram.handlers.watchlist import format_watchlist


def test_format_watchlist_lists_tickers():
    text = format_watchlist(["GAZP", "SBER"])
    assert "GAZP" in text and "SBER" in text and "watch" in text.lower()


def test_format_watchlist_empty():
    text = format_watchlist([])
    assert "пуст" in text.lower() and "/watch" in text
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/telegram/handlers/watchlist.py
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.watchlist import add_to_watchlist, list_watchlist, remove_from_watchlist
from roaring_kittens.deps import Deps

router = Router()

NOT_OWNER = "🔒 Watchlist доступен только владельцу — алерты по нему идут владельцу."


def format_watchlist(tickers: list[str]) -> str:
    if not tickers:
        return ("👁 Watchlist пуст.\n"
                "<code>/watch SBER</code> — следить за бумагой: impact-алерты по новостям "
                "и движение ≥5% за день.")
    lines = ["👁 <b>Watchlist:</b>", ""]
    lines += [f"• {t}" for t in tickers]
    lines += ["", "Убрать: <code>/unwatch ТИКЕР</code>"]
    return "\n".join(lines)


async def _owner_or_none(message: Message, deps: Deps) -> int | None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return None
    return owner_id


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/watch SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    async with deps.session_factory() as session:
        added = await add_to_watchlist(session, owner_id, instrument.ticker)
        await session.commit()
    await message.answer(
        f"👁 {instrument.ticker} {'добавлен в watchlist' if added else 'уже в watchlist'}. "
        f"Алерты: значимые новости + движение ≥5% за день.")


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/unwatch SBER</code>")
        return
    ticker = command.args.split()[0].upper()
    async with deps.session_factory() as session:
        removed = await remove_from_watchlist(session, owner_id, ticker)
        await session.commit()
    await message.answer(f"👁 {ticker} {'убран' if removed else 'и не был в watchlist'}.")


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    async with deps.session_factory() as session:
        tickers = await list_watchlist(session, owner_id)
    await message.answer(format_watchlist(tickers))
```

`handlers/__init__.py`: добавить `watchlist` в импорт и `all_routers.include_router(watchlist.router)`.

`start.py` HELP_TEXT, блок владельца, добавить:

```python
    "• <code>/watch ТИКЕР</code> — следить: impact-алерты + движение ≥5%\n"
```

- [ ] **Step 3: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/telegram tests/test_watchlist_render.py
git commit -m "feat: /watch /unwatch /watchlist commands"
```

---

### Task 11: README

- [ ] **Step 1: Обновить шапку и добавить раздел**

Шапка: «**Сейчас (Phase 4a):** реактивность (5-мин News Watcher, Impact Classifier,
HIGH→авто-комитет, quiet hours, /watch, прайс-алерты ≥5%), память и тезисы, комитет,
Trust Loop… **Дальше (Phase 4b):** мультитенантность для друзей.»

Раздел после «Память и тезисы»:

```markdown
## Реактивность (Phase 4a)

Новости опрашиваются каждые 5 минут. Для тикеров с тезисом работает Thesis Validator;
для остальных тикеров портфеля и /watch-списка — Impact Classifier (gpt-4o-mini:
critical/high/medium/low/noise). HIGH → алерт + авто-комитет (≤1/сутки на тикер),
critical (делистинг, санкции на компанию, слом тезиса) — сквозь тихие часы и троттлинг.
Тихие часы 22:00–08:00 МСК: несрочное копится в буфер и приходит перед утренним
дайджестом. Троттлинг ≤3 алерта/час. Прайс-алерт: |движение| ≥5% от вчерашнего
закрытия (раз в день на тикер, торговые часы).
```

- [ ] **Step 2: Commit**

```bash
git add README.md && git commit -m "docs: phase 4a README"
```

---

### Task 12: Деплой + E2E

- [ ] **Step 1: Deploy**

```bash
railway up --service app --ci
```

- [ ] **Step 2: MANUAL — E2E-чеклист**

- [ ] Логи: `news_polled` каждые 5 минут (было 30)
- [ ] `/watch LKOH` → подтверждение; `/watchlist` → список; `/unwatch LKOH` → убран
- [ ] При значимой новости по watchlist-тикеру: «⚡️ HIGH — …» + авто-комитет (в usage_log — операция impact_check)
- [ ] Ночью (22:00–08:00) несрочные алерты не приходят; утром перед дайджестом — «🌙 Ночью накопилось»
- [ ] При |движении| ≥5% по позиции/watchlist — «📈/📉 TICKER ±X% за день» (раз в день)
- [ ] Слом тезиса — приходит и ночью (critical)
- [ ] Троттлинг: >3 несрочных за час — остальные утром

- [ ] **Step 3: Тег**

```bash
git tag phase-4a && git push origin phase-4a
```

---

## Self-review checklist (выполнен при написании)

- **Spec coverage §7/§9:** 5-мин опрос ✅ (T7) · Impact Classifier по критериям спеки ✅ (T5) · HIGH→полный комитет с guard ✅ (T7) · critical override ✅ (T5-T7, слом тезиса = critical в T6) · quiet hours 22-08 с буфером в дайджест ✅ (T3, T9) · троттлинг ≤3/час, слабые группируются (буфер) ✅ (T3) · watchlist + /watch ✅ (T1-T2, T10) · hard alert по цене ✅ (T8)
- **Не дублируем алерты:** validate_theses возвращает handled-set, impact_scan их пропускает (T6-T7); GENERIC_NEWS_TICKER_CAP переиспользуется ✅
- **Типы согласованы:** `send_alert(deps, bot, chat_id, text, critical=, keyboard=) -> str` единый в T3/T6/T7/T8; `list_watchlist(session, owner_id)` в T2/T7/T8/T10; `map_last_prices` (T4) в get_last_prices; `drain_alerts` (T2) в T9; `chunk_lines` переиспользован из committee/render ✅
- **Placeholder scan:** полный код в каждом шаге ✅
- **Cost-контроль:** impact_check — mini и только на реально новых новостях ≤3 тикеров; ночью HIGH-комитеты не гоняем; прайс-кэш prev_close ✅
- **Приватность:** watchlist owner-only; все алерты идут только владельцу ✅
