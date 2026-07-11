# Phase 1.5 «Trust Loop» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот начинает сохранять каждый свой разбор (`calls`), ночью оценивает их против цены и IMOEX, показывает честный `/track` с промахами, отвечает на «докупать?» зная реальную позицию владельца, флагает смену собственного мнения и умеет ретро-посеять track-record на день 1.

**Architecture:** Поверх Phase 1: две новых таблицы (`calls`, `call_scores`) + репозиторий; модуль бенчмарка IMOEX (MOEX ISS candles, без auth); чистые функции вердикта/статистики + ночной APScheduler-джоб; расширение `_analyze_and_edit` (запись вызова, позиция владельца, прошлое мнение); команды `/track` (всем) и `/seed_retro` (владельцу).

**Tech Stack:** существующий (Python 3.12, aiogram 3, SQLAlchemy async, httpx, APScheduler). Новых зависимостей НЕТ.

**Verification model:** локального Python на машине нет — тесты гоняются в GitHub Actions CI (push → `gh run watch`), задачи батчуются по 2–4 на пуш. Деплой: `railway up --service app --ci`.

**Ключевые решения (из продуктового разбора 2026-07-05):**
- Вердикт — **относительно IMOEX**: bullish «hit» только если бумага выросла И обогнала индекс.
- Горизонты скоринга: 5 / 20 / 60 календарных дней; основной для витрины — 20.
- `/track` обязан показывать «❌ Худшие промахи» и бейзлайн («IMOEX рос в N% окон»).
- Позиция подаётся аналитику ТОЛЬКО если спрашивает владелец (приватность).
- Neutral «hit» = |excess| ≤ 3 пп (документированная константа).

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── db/
│   ├── calls.py            # NEW: CallRecord/ScoredCall + save/query репозиторий
│   ├── tables.py           # MOD: + calls, call_scores
│   └── ...
├── broker/
│   └── benchmark.py        # NEW: IMOEX ISS candles + return_between
├── scoring.py              # NEW: evaluate_call, build_track_stats, score_due_calls
├── scheduler.py            # MOD: + ночной cron скоринга
├── ai/analyst.py           # MOD: + position_note в промпт
├── digest/morning.py       # MOD: spotlight пишет call
└── telegram/
    ├── formatting.py       # MOD: + format_prev_call_note, format_track
    └── handlers/
        ├── ask.py          # MOD: запись call, позиция, прошлое мнение
        ├── track.py        # NEW: /track
        ├── seed.py         # NEW: /seed_retro (owner-only)
        └── __init__.py     # MOD: + track, seed
db/schema.sql               # MOD: + 2 таблицы
tests/
├── test_calls_repo.py      # NEW (integration, TEST_DATABASE_URL)
├── test_benchmark.py       # NEW
├── test_scoring.py         # NEW
├── test_formatting.py      # MOD: + prev-note, track
├── test_analyst.py         # MOD: + position_note
└── conftest.py             # MOD: truncate calls, call_scores
```

---

### Task 1: Схема — таблицы calls и call_scores

**Files:**
- Modify: `db/schema.sql`
- Modify: `src/roaring_kittens/db/tables.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Дописать в db/schema.sql (перед usage_log)**

```sql
CREATE TABLE IF NOT EXISTS calls (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    asked_by      BIGINT NOT NULL,
    ticker        VARCHAR(20) NOT NULL,
    figi          VARCHAR(20) NOT NULL,
    source        VARCHAR(20) NOT NULL,          -- 'ask' | 'spotlight' | 'retro'
    question      TEXT,
    stance        VARCHAR(10) NOT NULL,          -- 'bullish' | 'bearish' | 'neutral'
    confidence    FLOAT NOT NULL,
    summary       TEXT NOT NULL,
    price_at_call NUMERIC,                       -- NULL => не скорится
    news_urls     TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_calls_ticker_created ON calls (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS call_scores (
    call_id          UUID NOT NULL REFERENCES calls(id),
    horizon_days     INTEGER NOT NULL,           -- 5 | 20 | 60
    stock_return_pct NUMERIC NOT NULL,
    imoex_return_pct NUMERIC NOT NULL,
    verdict          VARCHAR(10) NOT NULL,       -- 'hit' | 'miss'
    scored_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, horizon_days)
);
```

- [ ] **Step 2: Дописать в src/roaring_kittens/db/tables.py (после bot_state)**

```python
from sqlalchemy import BigInteger, Float, ForeignKey  # добавить к существующим импортам

calls = Table(
    "calls", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("asked_by", BigInteger, nullable=False),
    Column("ticker", String(20), nullable=False),
    Column("figi", String(20), nullable=False),
    Column("source", String(20), nullable=False),
    Column("question", Text),
    Column("stance", String(10), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("summary", Text, nullable=False),
    Column("price_at_call", Numeric),
    Column("news_urls", ARRAY(Text), nullable=False, server_default=text("'{}'")),
)

call_scores = Table(
    "call_scores", metadata,
    Column("call_id", UUID(as_uuid=True), ForeignKey("calls.id"), primary_key=True),
    Column("horizon_days", Integer, primary_key=True),
    Column("stock_return_pct", Numeric, nullable=False),
    Column("imoex_return_pct", Numeric, nullable=False),
    Column("verdict", String(10), nullable=False),
    Column("scored_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
```

- [ ] **Step 3: В tests/conftest.py расширить TRUNCATE**

```python
    await conn.execute("TRUNCATE news_events, usage_log, bot_state, call_scores, calls")
```

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db/tables.py tests/conftest.py
git commit -m "feat: calls and call_scores tables"
```

---

### Task 2: Репозиторий calls (TDD, integration)

**Files:**
- Create: `src/roaring_kittens/db/calls.py`
- Test: `tests/test_calls_repo.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_calls_repo.py
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.calls import (
    count_calls_by_source, count_unscored, get_last_call, get_scored_calls,
    get_unscored_calls, save_call, save_score,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

NOW = datetime.now(tz=timezone.utc)


async def _save(session, *, ticker="SBER", created_at=None, stance="bullish",
                price=Decimal("280"), source="ask"):
    return await save_call(
        session, asked_by=111, ticker=ticker, figi="BBG004730N88", source=source,
        question=None, stance=stance, confidence=0.7, summary="s",
        price_at_call=price, news_urls=["https://x/1"], created_at=created_at)


async def test_save_and_get_last_call_within_window(db_session_factory):
    async with db_session_factory() as session:
        await _save(session, created_at=NOW - timedelta(days=2))
        await _save(session, created_at=NOW - timedelta(days=30))  # вне окна 7д
        await session.commit()
    async with db_session_factory() as session:
        last = await get_last_call(session, "SBER", within_days=7)
        assert last is not None and last.stance == "bullish"
        assert (NOW - last.created_at).days == 2
        assert await get_last_call(session, "GAZP", within_days=7) is None


async def test_unscored_respects_horizon_price_and_existing_scores(db_session_factory):
    async with db_session_factory() as session:
        old = await _save(session, created_at=NOW - timedelta(days=10))
        fresh = await _save(session, created_at=NOW - timedelta(days=1))
        no_price = await _save(session, created_at=NOW - timedelta(days=10), price=None)
        await session.commit()
    async with db_session_factory() as session:
        due = await get_unscored_calls(session, horizon_days=5, now=NOW)
        ids = {c.id for c in due}
        assert old in ids or old in {c.id for c in due}  # старый со свежей ценой — due
        assert fresh not in ids and no_price not in ids
        await save_score(session, old, 5, Decimal("2.0"), Decimal("1.0"), "hit")
        await save_score(session, old, 5, Decimal("2.0"), Decimal("1.0"), "hit")  # идемпотентно
        await session.commit()
    async with db_session_factory() as session:
        assert old not in {c.id for c in await get_unscored_calls(session, 5, NOW)}
        scored = await get_scored_calls(session)
        assert len(scored) == 1 and scored[0].verdict == "hit"
        assert await count_calls_by_source(session, "retro") == 0
        # без единой оценки остался только fresh; no_price (NULL) не считается
        assert await count_unscored(session) == 1
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/calls.py
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import Date, cast, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import call_scores, calls


@dataclass(frozen=True)
class CallRecord:
    id: UUIDType
    created_at: datetime
    asked_by: int
    ticker: str
    figi: str
    source: str
    question: str | None
    stance: str
    confidence: float
    summary: str
    price_at_call: Decimal | None
    news_urls: list[str]


@dataclass(frozen=True)
class ScoredCall:
    ticker: str
    stance: str
    created_at: datetime
    source: str
    horizon_days: int
    stock_return_pct: Decimal
    imoex_return_pct: Decimal
    verdict: str

    @property
    def excess_pp(self) -> Decimal:
        return self.stock_return_pct - self.imoex_return_pct


def _row_to_call(r) -> CallRecord:
    return CallRecord(id=r.id, created_at=r.created_at, asked_by=r.asked_by,
                      ticker=r.ticker, figi=r.figi, source=r.source, question=r.question,
                      stance=r.stance, confidence=r.confidence, summary=r.summary,
                      price_at_call=r.price_at_call, news_urls=list(r.news_urls))


async def save_call(session: AsyncSession, *, asked_by: int, ticker: str, figi: str,
                    source: str, question: str | None, stance: str, confidence: float,
                    summary: str, price_at_call: Decimal | None, news_urls: list[str],
                    created_at: datetime | None = None) -> UUIDType:
    values = dict(asked_by=asked_by, ticker=ticker, figi=figi, source=source,
                  question=question, stance=stance, confidence=confidence,
                  summary=summary, price_at_call=price_at_call, news_urls=news_urls)
    if created_at is not None:  # retro-посев пишет прошлую дату
        values["created_at"] = created_at
    result = await session.execute(calls.insert().values(**values).returning(calls.c.id))
    return result.scalar_one()


async def get_last_call(session: AsyncSession, ticker: str,
                        within_days: int = 7) -> CallRecord | None:
    since = datetime.now(tz=timezone.utc) - timedelta(days=within_days)
    row = (await session.execute(
        select(calls).where(calls.c.ticker == ticker, calls.c.created_at >= since)
        .order_by(calls.c.created_at.desc()).limit(1))).first()
    return _row_to_call(row) if row else None


async def get_unscored_calls(session: AsyncSession, horizon_days: int,
                             now: datetime) -> list[CallRecord]:
    cutoff = now - timedelta(days=horizon_days)
    already = exists(select(1).where(call_scores.c.call_id == calls.c.id,
                                     call_scores.c.horizon_days == horizon_days))
    rows = (await session.execute(
        select(calls).where(calls.c.created_at <= cutoff,
                            calls.c.price_at_call.isnot(None), ~already))).fetchall()
    return [_row_to_call(r) for r in rows]


async def save_score(session: AsyncSession, call_id: UUIDType, horizon_days: int,
                     stock_return_pct: Decimal, imoex_return_pct: Decimal,
                     verdict: str) -> None:
    stmt = insert(call_scores).values(
        call_id=call_id, horizon_days=horizon_days, stock_return_pct=stock_return_pct,
        imoex_return_pct=imoex_return_pct, verdict=verdict,
    ).on_conflict_do_nothing(index_elements=["call_id", "horizon_days"])
    await session.execute(stmt)


async def get_scored_calls(session: AsyncSession) -> list[ScoredCall]:
    j = calls.join(call_scores, calls.c.id == call_scores.c.call_id)
    rows = (await session.execute(
        select(calls.c.ticker, calls.c.stance, calls.c.created_at, calls.c.source,
               call_scores.c.horizon_days, call_scores.c.stock_return_pct,
               call_scores.c.imoex_return_pct, call_scores.c.verdict)
        .select_from(j))).fetchall()
    return [ScoredCall(*r) for r in rows]


async def count_calls_by_source(session: AsyncSession, source: str) -> int:
    return (await session.execute(
        select(func.count()).where(calls.c.source == source))).scalar_one()


async def count_unscored(session: AsyncSession) -> int:
    """Скорибельные вызовы без единой оценки (NULL-price не считаем — они не зреют)."""
    any_score = exists(select(1).where(call_scores.c.call_id == calls.c.id))
    return (await session.execute(
        select(func.count()).select_from(calls)
        .where(~any_score, calls.c.price_at_call.isnot(None)))).scalar_one()


async def get_retro_seeded_keys(session: AsyncSession) -> set[tuple[str, date]]:
    """(ticker, дата as-of) уже посеянных retro-вызовов — для идемпотентного /seed_retro."""
    rows = (await session.execute(
        select(calls.c.ticker, cast(calls.c.created_at, Date))
        .where(calls.c.source == "retro"))).fetchall()
    return {(r[0], r[1]) for r in rows}
```

- [ ] **Step 3: Push → CI зелёный (обе задачи), Commit**

```bash
git add src/roaring_kittens/db/calls.py tests/test_calls_repo.py
git commit -m "feat: calls repository (save, last-call, unscored, scores)"
```

---

### Task 3: Бенчмарк IMOEX (MOEX ISS candles)

**Files:**
- Create: `src/roaring_kittens/broker/benchmark.py`
- Test: `tests/test_benchmark.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_benchmark.py
from datetime import date
from decimal import Decimal

import httpx

from roaring_kittens.broker.benchmark import (
    fetch_imoex_closes, parse_iss_candles, return_between,
)

ISS_CANDLES = {
    "candles": {
        "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
        "data": [
            [3000, 3010.5, 3020, 2990, 0, 0, "2026-06-01 00:00:00", "2026-06-01 23:59:59"],
            [3010, 3050.0, 3060, 3000, 0, 0, "2026-06-02 00:00:00", "2026-06-02 23:59:59"],
            [3050, 3100.0, 3110, 3040, 0, 0, "2026-06-05 00:00:00", "2026-06-05 23:59:59"],
        ],
    }
}


def test_parse_iss_candles():
    closes = parse_iss_candles(ISS_CANDLES)
    assert closes[0] == (date(2026, 6, 1), Decimal("3010.5"))
    assert len(closes) == 3


def test_return_between_uses_nearest_trading_days():
    closes = parse_iss_candles(ISS_CANDLES)
    # start 2026-06-03 (выходной) -> ближайший ПОСЛЕ = 06-05; end 06-10 -> ближайший ДО = 06-05
    assert return_between(closes, date(2026, 6, 1), date(2026, 6, 5)) == Decimal("3.0")
    assert return_between(closes, date(2026, 6, 3), date(2026, 6, 10)) == Decimal("0.0")
    assert return_between(closes, date(2026, 7, 1), date(2026, 7, 10)) is None  # нет данных


async def test_fetch_imoex_closes_via_transport():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=ISS_CANDLES))
    closes = await fetch_imoex_closes(date(2026, 6, 1), date(2026, 6, 10), transport=transport)
    assert len(closes) == 3
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/broker/benchmark.py
"""Бенчмарк IMOEX: дневные свечи индекса из публичного MOEX ISS (без auth)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx
import structlog

from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()

IMOEX_CANDLES_URL = ("https://iss.moex.com/iss/engines/stock/markets/index/"
                     "securities/IMOEX/candles.json?interval=24&from={frm}&till={till}")


def parse_iss_candles(payload: dict) -> list[tuple[date, Decimal]]:
    block = payload["candles"]
    ci, bi = block["columns"].index("close"), block["columns"].index("begin")
    out = []
    for row in block["data"]:
        d = datetime.strptime(str(row[bi])[:10], "%Y-%m-%d").date()
        out.append((d, Decimal(str(row[ci]))))
    return sorted(out)


@retry_async(attempts=2, base_delay=2.0)
async def fetch_imoex_closes(frm: date, till: date,
                             transport: httpx.BaseTransport | None = None
                             ) -> list[tuple[date, Decimal]]:
    url = IMOEX_CANDLES_URL.format(frm=frm.isoformat(), till=till.isoformat())
    async with httpx.AsyncClient(transport=transport, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_iss_candles(resp.json())


def return_between(closes: list[tuple[date, Decimal]], start: date,
                   end: date) -> Decimal | None:
    """Доходность %, ближайший торговый день >= start до ближайшего <= end."""
    start_close = next((c for d, c in closes if d >= start), None)
    end_close = next((c for d, c in reversed(closes) if d <= end), None)
    if start_close is None or end_close is None or not start_close:
        return None
    start_day = next(d for d, c in closes if d >= start)
    end_day = next(d for d, c in reversed(closes) if d <= end)
    if end_day < start_day:
        return None
    return ((end_close - start_close) / start_close * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/broker/benchmark.py tests/test_benchmark.py
git commit -m "feat: IMOEX benchmark via MOEX ISS candles"
```

---

### Task 4: Вердикт и статистика (чистая логика)

**Files:**
- Create: `src/roaring_kittens/scoring.py` (часть 1: pure-функции)
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_scoring.py
from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.scoring import build_track_stats, evaluate_call

D = Decimal


def test_bullish_needs_growth_and_beating_index():
    assert evaluate_call("bullish", D("5"), D("2")) == "hit"
    assert evaluate_call("bullish", D("2"), D("5")) == "miss"   # вырос, но хуже IMOEX
    assert evaluate_call("bullish", D("-1"), D("-3")) == "miss"  # обогнал, но упал


def test_bearish_symmetric():
    assert evaluate_call("bearish", D("-4"), D("-1")) == "hit"
    assert evaluate_call("bearish", D("1"), D("2")) == "miss"


def test_neutral_band():
    assert evaluate_call("neutral", D("2"), D("0")) == "hit"    # |excess|=2 <= 3
    assert evaluate_call("neutral", D("6"), D("1")) == "miss"   # |excess|=5 > 3


def _sc(stance, verdict, excess, horizon=20, ticker="SBER"):
    return ScoredCall(ticker=ticker, stance=stance,
                      created_at=datetime.now(tz=timezone.utc), source="ask",
                      horizon_days=horizon, stock_return_pct=D(excess) + D("1"),
                      imoex_return_pct=D("1"), verdict=verdict)


def test_build_track_stats_aggregates_and_ranks_worst():
    rows = [_sc("bullish", "hit", "4"), _sc("bullish", "miss", "-9"),
            _sc("bearish", "hit", "-15", ticker="LKOH"),   # большой |excess|, но ХИТ — не промах
            _sc("neutral", "miss", "10", ticker="GAZP"),   # промах с ПОЛОЖИТЕЛЬНЫМ excess
            _sc("bearish", "miss", "-2", ticker="VTBR"),
            _sc("bullish", "hit", "3", horizon=5)]  # другой горизонт — не в основной срез
    stats = build_track_stats(rows, primary_horizon=20)
    assert stats.total_scored == 5
    assert stats.by_stance["bullish"] == (1, 2)
    # худшие = ТОЛЬКО промахи, по |excess| убыв.; bearish-хит с -15 не вытесняет
    assert [w.excess_pp for w in stats.worst] == [D("10"), D("-9"), D("-2")]
    assert stats.imoex_up_windows == 5  # imoex_return=1 > 0 во всех 5
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/scoring.py
from dataclasses import dataclass, field
from decimal import Decimal

from roaring_kittens.db.calls import ScoredCall

NEUTRAL_BAND_PP = Decimal("3")
HORIZONS = (5, 20, 60)
PRIMARY_HORIZON = 20


def evaluate_call(stance: str, stock_return_pct: Decimal,
                  imoex_return_pct: Decimal) -> str:
    """Вердикт относительно бенчмарка: рост при отставании от IMOEX — не победа."""
    excess = stock_return_pct - imoex_return_pct
    if stance == "bullish":
        return "hit" if stock_return_pct > 0 and excess > 0 else "miss"
    if stance == "bearish":
        return "hit" if stock_return_pct < 0 and excess < 0 else "miss"
    return "hit" if abs(excess) <= NEUTRAL_BAND_PP else "miss"


@dataclass
class TrackStats:
    primary_horizon: int
    total_scored: int
    by_stance: dict[str, tuple[int, int]]   # stance -> (hits, total)
    avg_excess_pp: Decimal
    imoex_up_windows: int                   # окон с ростом IMOEX (для бейзлайна)
    worst: list[ScoredCall] = field(default_factory=list)
    per_horizon: dict[int, tuple[int, int]] = field(default_factory=dict)


def build_track_stats(rows: list[ScoredCall], primary_horizon: int = PRIMARY_HORIZON,
                      worst_n: int = 3) -> TrackStats:
    per_horizon: dict[int, tuple[int, int]] = {}
    for r in rows:
        h, t = per_horizon.get(r.horizon_days, (0, 0))
        per_horizon[r.horizon_days] = (h + (r.verdict == "hit"), t + 1)

    primary = [r for r in rows if r.horizon_days == primary_horizon]
    by_stance: dict[str, tuple[int, int]] = {}
    for r in primary:
        h, t = by_stance.get(r.stance, (0, 0))
        by_stance[r.stance] = (h + (r.verdict == "hit"), t + 1)

    avg = (sum(r.excess_pp for r in primary) / len(primary)).quantize(Decimal("0.1")) \
        if primary else Decimal("0")
    # Сначала фильтруем промахи, потом ранжируем по |excess| (= величина ошибки,
    # корректна для любого stance: bearish-промах имеет ПОЛОЖИТЕЛЬНЫЙ excess).
    misses = [r for r in primary if r.verdict == "miss"]
    worst = sorted(misses, key=lambda r: abs(r.excess_pp), reverse=True)[:worst_n]
    return TrackStats(primary_horizon=primary_horizon, total_scored=len(primary),
                      by_stance=by_stance, avg_excess_pp=avg,
                      imoex_up_windows=sum(1 for r in primary if r.imoex_return_pct > 0),
                      worst=worst, per_horizon=per_horizon)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/scoring.py tests/test_scoring.py
git commit -m "feat: benchmark-relative verdicts and track stats"
```

---

### Task 5: Ночной скоринг-джоб + cron

**Files:**
- Modify: `src/roaring_kittens/scoring.py` (часть 2: джоб)
- Modify: `src/roaring_kittens/scheduler.py`

- [ ] **Step 1: Дописать джоб в scoring.py**

```python
# добавить в src/roaring_kittens/scoring.py
from datetime import datetime, timedelta, timezone

import structlog

from roaring_kittens.broker.benchmark import fetch_imoex_closes, return_between
from roaring_kittens.db.calls import get_unscored_calls, save_score

log = structlog.get_logger()


async def score_due_calls(deps) -> int:
    """Оценивает все вызовы, дозревшие до горизонтов 5/20/60 дней. Возвращает счётчик."""
    now = datetime.now(tz=timezone.utc)
    frm = (now - timedelta(days=max(HORIZONS) + 120)).date()  # запас под retro-посев
    try:
        imoex = await fetch_imoex_closes(frm, now.date())
    except Exception as exc:
        log.error("scoring_imoex_unavailable", error=str(exc))
        return 0
    scored = 0
    for horizon in HORIZONS:
        async with deps.session_factory() as session:
            due = await get_unscored_calls(session, horizon, now)
        for call in due:
            lookback = (now - call.created_at).days + 15
            try:
                candles = await deps.broker.get_daily_candles(call.figi, days=lookback)
            except Exception as exc:
                log.warning("scoring_candles_failed", ticker=call.ticker, error=str(exc))
                continue
            closes = sorted((c.day, c.close) for c in candles)  # API-порядку не доверяем (как tech.py)
            start = call.created_at.date()
            end = (call.created_at + timedelta(days=horizon)).date()
            stock_ret = return_between(closes, start, end)
            imoex_ret = return_between(imoex, start, end)
            if stock_ret is None or imoex_ret is None:
                continue
            verdict = evaluate_call(call.stance, stock_ret, imoex_ret)
            async with deps.session_factory() as session:
                await save_score(session, call.id, horizon, stock_ret, imoex_ret, verdict)
                await session.commit()
            scored += 1
    log.info("scoring_done", scored=scored)
    return scored
```

- [ ] **Step 2: Cron в scheduler.py → build_scheduler (после morning_digest)**

```python
from roaring_kittens.scoring import score_due_calls

    scheduler.add_job(score_due_calls, "cron", hour=23, minute=45, args=[deps],
                      id="score_calls", max_instances=1, coalesce=True)
```

- [ ] **Step 3: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/scoring.py src/roaring_kittens/scheduler.py
git commit -m "feat: nightly call scoring vs price and IMOEX"
```

---

### Task 6: Позиционно-осведомлённый аналитик

**Files:**
- Modify: `src/roaring_kittens/ai/analyst.py`
- Test: `tests/test_analyst.py` (дополнить)

- [ ] **Step 1: Падающий тест (в tests/test_analyst.py)**

```python
def test_messages_include_position_note_when_given():
    msgs = build_analyst_messages(
        "SBER", TECH, NEWS, question="докупать?",
        position_note="Позиция: 500 шт по 280 ₽ (P&L +5.4%), вес 12% портфеля.")
    user = msgs[1]["content"]
    assert "500 шт по 280" in user and "вес 12%" in user


def test_messages_without_position_have_no_position_block():
    msgs = build_analyst_messages("SBER", TECH, NEWS, question=None)
    assert "Позиция" not in msgs[1]["content"]
```

- [ ] **Step 2: Реализовать (в ai/analyst.py)**

`build_analyst_messages` и `run_analyst` получают опциональный `position_note`:

```python
def build_analyst_messages(ticker: str, tech: TechSummary | None,
                           news: list[NewsItem], question: str | None,
                           position_note: str | None = None) -> list[dict]:
    tech_text = tech.as_text() if tech else "Технических данных недостаточно."
    user = (
        f"Тикер: {ticker}\n\n"
        f"Техника:\n{tech_text}\n\n"
        f"Новости (последние):\n{_format_news(news)}\n"
    )
    if position_note:
        user += f"\n{position_note}\n"
    if question:
        user += f"\nВопрос пользователя: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def run_analyst(llm: LLM, ticker: str, tech: TechSummary | None,
                      news: list[NewsItem], question: str | None,
                      position_note: str | None = None) -> AnalystReport:
    messages = build_analyst_messages(ticker, tech, news, question, position_note)
    return await llm.parse(model=ANALYST_MODEL, operation="analyst",
                           messages=messages, schema=AnalystReport)
```

В SYSTEM_PROMPT дописать строку после «Правила:»-блока:

```
- Если дан блок «Позиция» — рассуждай относительно реального входа и веса позиции
  (докупать/держать/сокращать), а не абстрактно.
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/ai/analyst.py tests/test_analyst.py
git commit -m "feat: analyst reasons about the owner's actual position"
```

---

### Task 7: Запись вызовов + позиция + «прошлое мнение» в /ask

**Files:**
- Modify: `src/roaring_kittens/telegram/formatting.py`
- Modify: `src/roaring_kittens/telegram/handlers/ask.py`
- Test: `tests/test_formatting.py` (дополнить)

- [ ] **Step 1: Падающий тест форматтера прошлого мнения**

```python
# добавить в tests/test_formatting.py
from datetime import timedelta
from roaring_kittens.telegram.formatting import format_prev_call_note

_NOW = datetime.now(tz=timezone.utc)


def test_prev_call_note_same_stance():
    note = format_prev_call_note("neutral", 0.6, _NOW - timedelta(days=3), "neutral", _NOW)
    assert "3 дн" in note and "⚪️" in note and "изменилось" not in note


def test_prev_call_note_flags_stance_flip():
    note = format_prev_call_note("bullish", 0.7, _NOW - timedelta(days=2), "bearish", _NOW)
    assert "🟢" in note and "мнение изменилось" in note
```

- [ ] **Step 2: Реализовать форматтер (в formatting.py)**

```python
# добавить в src/roaring_kittens/telegram/formatting.py
from datetime import datetime


def format_prev_call_note(prev_stance: str, prev_confidence: float,
                          prev_at: datetime, new_stance: str, now: datetime) -> str:
    days = (now - prev_at).days
    when = "сегодня" if days == 0 else f"{days} дн назад"
    note = (f"🕰 Прошлый разбор ({when}): {STANCE_EMOJI[prev_stance]} {prev_stance} "
            f"{round(prev_confidence * 100)}%")
    if prev_stance != new_stance:
        note += " → ⚠️ мнение изменилось"
    return note
```

И вставка в `format_analyst_report` — новый опциональный параметр:

```python
def format_analyst_report(r: AnalystReport, low_data: bool = False,
                          sources: list[NewsItem] | None = None,
                          prev_note: str | None = None) -> str:
    ...  # существующее тело без изменений до финального блока
    if sources:
        lines += _format_sources(sources)
    if prev_note:
        lines += ["", prev_note]
    lines += ["", "<i>Это аналитический разбор, не инвестрекомендация.</i>"]
    return "\n".join(lines)
```

- [ ] **Step 3: Перепрошить `_analyze_and_edit` в ask.py**

Новая сигнатура — добавляется `asked_by`; внутри: прошлый вызов → позиция владельца → аналитик → запись call → рендер:

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from roaring_kittens.db.calls import get_last_call, save_call
from roaring_kittens.telegram.formatting import format_analyst_report, format_prev_call_note


async def build_position_note(deps: Deps, ticker: str) -> str | None:
    """Блок о реальной позиции владельца. None при сбое (не блокируем разбор)."""
    try:
        snap = await deps.broker.get_portfolio()
    except Exception as exc:
        log.warning("position_note_failed", error=str(exc))
        return None
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None:
        return "Позиция: у пользователя НЕТ этой бумаги в портфеле."
    weight = (pos.quantity * pos.current_price / snap.total_value * 100).quantize(Decimal("0.1")) \
        if snap.total_value else Decimal("0")
    return (f"Позиция: {pos.quantity} шт по {pos.avg_price} ₽ "
            f"(P&L {pos.pnl_pct:+}%), вес {weight}% портфеля.")


async def _analyze_and_edit(progress: Message, deps: Deps, instrument: Instrument,
                            question: str | None, asked_by: int) -> None:
    try:
        candles = await deps.broker.get_daily_candles(instrument.figi)
        tech = compute_tech_summary(candles)
        since = datetime.now(tz=timezone.utc) - timedelta(days=3)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [instrument.ticker], since=since)
            prev = await get_last_call(session, instrument.ticker)
        owner_id = await fetch_owner_id(deps.session_factory)
        position_note = await build_position_note(deps, instrument.ticker) \
            if asked_by == owner_id else None
        report = await run_analyst(deps.llm, instrument.ticker, tech, news,
                                   question, position_note)
    except Exception as exc:
        log.error("ask_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Не смог разобрать {instrument.ticker} — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/ask {instrument.ticker}</code>"
        )
        return

    try:  # запись вызова не должна ронять ответ пользователю
        async with deps.session_factory() as session:
            await save_call(session, asked_by=asked_by, ticker=instrument.ticker,
                            figi=instrument.figi, source="ask", question=question,
                            stance=report.stance, confidence=report.confidence,
                            summary=report.summary,
                            price_at_call=tech.last_close if tech else None,
                            news_urls=[n.url for n in news])
            await session.commit()
    except Exception as exc:
        log.error("save_call_failed", ticker=instrument.ticker, error=str(exc))

    now = datetime.now(tz=timezone.utc)
    prev_note = format_prev_call_note(prev.stance, prev.confidence, prev.created_at,
                                      report.stance, now) if prev else None
    low_data = tech is None or not news
    await progress.edit_text(
        format_analyst_report(report, low_data=low_data, sources=news or None,
                              prev_note=prev_note)
    )
```

Оба вызывающих места передают `asked_by`:
- в `cmd_ask`: `await _analyze_and_edit(progress, deps, instrument, question, asked_by=message.from_user.id)`
- в `cb_run_ask`: `await _analyze_and_edit(callback.message, deps, instrument, None, asked_by=callback.from_user.id)`

- [ ] **Step 4: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/telegram/formatting.py src/roaring_kittens/telegram/handlers/ask.py tests/test_formatting.py
git commit -m "feat: persist every call, feed owner position, flag stance flips"
```

---

### Task 8: /track — честный дашборд

**Files:**
- Modify: `src/roaring_kittens/telegram/formatting.py` (format_track)
- Create: `src/roaring_kittens/telegram/handlers/track.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`
- Test: `tests/test_formatting.py` (дополнить)

- [ ] **Step 1: Падающий тест**

```python
# добавить в tests/test_formatting.py
from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.scoring import TrackStats
from roaring_kittens.telegram.formatting import format_track


def test_format_track_shows_hitrate_baseline_and_misses():
    worst = [ScoredCall(ticker="SBER", stance="bullish",
                        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc), source="ask",
                        horizon_days=20, stock_return_pct=Decimal("-8.3"),
                        imoex_return_pct=Decimal("1.0"), verdict="miss")]
    stats = TrackStats(primary_horizon=20, total_scored=10,
                       by_stance={"bullish": (4, 7), "neutral": (2, 3)},
                       avg_excess_pp=Decimal("1.8"), imoex_up_windows=6,
                       worst=worst, per_horizon={5: (5, 8), 20: (6, 10)})
    text = format_track(stats, unscored=4)
    assert "4/7" in text and "+1.8" in text
    assert "60%" in text                     # бейзлайн: 6/10 окон IMOEX рос
    assert "SBER" in text and "−9.3" in text  # excess промаха (−8.3−1.0), знак честный
    assert "единой оценки: 4" in text


def test_format_track_empty():
    stats = TrackStats(primary_horizon=20, total_scored=0, by_stance={},
                       avg_excess_pp=Decimal("0"), imoex_up_windows=0)
    assert "пока нет" in format_track(stats, unscored=2).lower()


def test_format_track_shows_horizons_while_primary_matures():
    # 5-дневные оценки уже есть, 20-дневное окно ещё не дозрело — НЕ «пока нет»
    stats = TrackStats(primary_horizon=20, total_scored=0, by_stance={},
                       avg_excess_pp=Decimal("0"), imoex_up_windows=0,
                       per_horizon={5: (3, 4)})
    text = format_track(stats, unscored=1)
    assert "5д: 3/4" in text and "зреет" in text.lower()
    assert "пока нет" not in text.lower()
```

- [ ] **Step 2: Реализовать format_track (в formatting.py)**

```python
# добавить в src/roaring_kittens/telegram/formatting.py
from roaring_kittens.scoring import TrackStats


def format_track(stats: TrackStats, unscored: int) -> str:
    # «пока нет» — только когда нет НИ ОДНОЙ оценки ни на одном горизонте
    if not stats.per_horizon:
        return ("📊 <b>Track record</b>\n\nОценённых вызовов пока нет — "
                f"вызовы зреют минимум 5 дней (без единой оценки: {unscored}).")
    lines = ["📊 <b>Track record</b>"]
    parts = [f"{h}д: {v[0]}/{v[1]}" for h, v in sorted(stats.per_horizon.items())]
    lines.append("По горизонтам (hit/всего): " + " · ".join(parts))
    if stats.total_scored == 0:  # 5-дневные оценки есть, основное окно ещё зреет
        lines += ["", f"Основное окно ({stats.primary_horizon} дн) ещё зреет — "
                      "разбивка по ставкам появится позже.",
                  "", f"Без единой оценки: {unscored}"]
        return "\n".join(lines)
    lines += ["", f"Окно {stats.primary_horizon} дн — {stats.total_scored} оценённых:"]
    for stance in ("bullish", "bearish", "neutral"):
        if stance in stats.by_stance:
            hits, total = stats.by_stance[stance]
            lines.append(f"{STANCE_EMOJI[stance]} {stance}: {hits}/{total} hit")
    sign = "+" if stats.avg_excess_pp >= 0 else "−"
    lines.append(f"Средний результат vs IMOEX: {sign}{abs(stats.avg_excess_pp)} пп")
    baseline = round(stats.imoex_up_windows / stats.total_scored * 100)
    lines.append(f"Бейзлайн: IMOEX рос в {baseline}% этих окон")
    if stats.worst:
        lines += ["", "❌ <b>Худшие промахи:</b>"]
        for w in stats.worst:
            esign = "+" if w.excess_pp >= 0 else "−"  # знак честный: bearish-промах = плюс
            lines.append(f"• {w.ticker} {STANCE_EMOJI[w.stance]} {w.created_at:%d.%m} "
                         f"→ {esign}{abs(w.excess_pp)} пп vs IMOEX")
    lines += ["", f"Без единой оценки: {unscored} (вызовы зреют 5/20/60 дней)"]
    return "\n".join(lines)
```

- [ ] **Step 3: Handler**

```python
# src/roaring_kittens/telegram/handlers/track.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.db.calls import count_unscored, get_scored_calls
from roaring_kittens.deps import Deps
from roaring_kittens.scoring import build_track_stats
from roaring_kittens.telegram.formatting import format_track

router = Router()


@router.message(Command("track"))
async def cmd_track(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        rows = await get_scored_calls(session)
        unscored = await count_unscored(session)
    await message.answer(format_track(build_track_stats(rows), unscored=unscored))
```

В `handlers/__init__.py`:

```python
from roaring_kittens.telegram.handlers import ask, digest, portfolio, start, track
...
all_routers.include_router(track.router)
```

- [ ] **Step 4: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/telegram tests/test_formatting.py
git commit -m "feat: /track honest hit-rate dashboard with worst misses and baseline"
```

---

### Task 9: Spotlight дайджеста тоже пишет call

**Files:**
- Modify: `src/roaring_kittens/digest/morning.py`

- [ ] **Step 1: В build_spotlight записать вызов**

`build_spotlight` получает `asked_by: int` (owner chat id, уже есть у вызывающего) и после успешного `run_analyst` сохраняет:

```python
# заменить build_spotlight в src/roaring_kittens/digest/morning.py
from roaring_kittens.db.calls import save_call


async def build_spotlight(deps: Deps, position: Position, asked_by: int) -> str | None:
    """Разбор дня для тихого утра (нет новостей) — переиспользует одиночный аналитик."""
    try:
        candles = await deps.broker.get_daily_candles(position.figi)
        tech = compute_tech_summary(candles)
        report = await run_analyst(deps.llm, position.ticker, tech, [], None)
    except Exception as exc:
        log.error("spotlight_failed", ticker=position.ticker, error=str(exc))
        return None
    try:
        async with deps.session_factory() as session:
            await save_call(session, asked_by=asked_by, ticker=position.ticker,
                            figi=position.figi, source="spotlight", question=None,
                            stance=report.stance, confidence=report.confidence,
                            summary=report.summary,
                            price_at_call=tech.last_close if tech else None,
                            news_urls=[])
            await session.commit()
    except Exception as exc:
        log.error("save_call_failed", ticker=position.ticker, error=str(exc))
    emoji = STANCE_EMOJI.get(report.stance, "")
    return f"🔎 <b>Разбор дня — {position.ticker}</b> {emoji}\n{report.summary}"
```

Вызов в `run_morning_digest`: `spotlight = await build_spotlight(deps, snap.positions[idx], asked_by=chat_id)`.

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/digest/morning.py
git commit -m "feat: digest spotlight records its call for scoring"
```

---

### Task 10: /seed_retro — ретро-посев track-record (owner-only)

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/seed.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`

- [ ] **Step 1: Реализовать**

```python
# src/roaring_kittens/telegram/handlers/seed.py
"""Ретро-посев: прогоняет аналитик по текущим позициям с as-of датой 60/30 дней назад
(только свечи, без новостей — их за прошлое не восстановить), сразу скорит.
Даёт видимый track-record в день 1 вместо дня 90. Стоимость ~2×N LLM-вызовов.
Идемпотентен: уже посеянные (тикер, as-of дата) пропускаются, поэтому перезапуск
после частичного сбоя безопасен, а накрутить track-record повторами нельзя."""
from datetime import datetime, timedelta, timezone

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.db.calls import get_retro_seeded_keys, save_call
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.scoring import score_due_calls

log = structlog.get_logger()
router = Router()

AS_OF_DAYS = (60, 30)
MAX_POSITIONS = 10


@router.message(Command("seed_retro"))
async def cmd_seed_retro(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer("🔒 Команда доступна только владельцу.")
        return
    async with deps.session_factory() as session:
        seeded_keys = await get_retro_seeded_keys(session)
    snap = await deps.broker.get_portfolio()
    if not snap.positions:
        await message.answer("Портфель пуст — сеять нечего.")
        return
    progress = await message.answer("🌱 Сею ретро-разборы (это ~1-2 минуты)…")
    now = datetime.now(tz=timezone.utc)
    seeded, skipped = 0, 0
    for pos in snap.positions[:MAX_POSITIONS]:
        try:
            candles = await deps.broker.get_daily_candles(pos.figi, days=150)
        except Exception as exc:
            log.warning("seed_candles_failed", ticker=pos.ticker, error=str(exc))
            continue
        candles = sorted(candles, key=lambda c: c.day)  # API-порядку не доверяем
        for days_ago in AS_OF_DAYS:
            as_of = now - timedelta(days=days_ago)
            if (pos.ticker, as_of.date()) in seeded_keys:
                skipped += 1
                continue
            past = [c for c in candles if c.day <= as_of.date()][-35:]
            tech = compute_tech_summary(past)
            if tech is None:
                continue
            try:
                report = await run_analyst(deps.llm, pos.ticker, tech, [], None)
            except Exception as exc:
                log.error("seed_analyst_failed", ticker=pos.ticker, error=str(exc))
                continue
            async with deps.session_factory() as session:
                await save_call(session, asked_by=owner_id, ticker=pos.ticker,
                                figi=pos.figi, source="retro", question=None,
                                stance=report.stance, confidence=report.confidence,
                                summary=report.summary, price_at_call=tech.last_close,
                                news_urls=[], created_at=as_of)
                await session.commit()
            seeded += 1
    scored = await score_due_calls(deps)
    await progress.edit_text(
        f"🌱 Посеяно {seeded} новых ретро-разборов "
        f"(пропущено существующих: {skipped}), оценено {scored}.\n"
        f"Смотри /track — у бота уже есть послужной список."
    )
```

В `handlers/__init__.py` добавить `seed` в импорт и `all_routers.include_router(seed.router)`.

- [ ] **Step 2: Обновить HELP_TEXT в start.py — секция владельца**

```python
    "• <code>/track</code> — послужной список бота (hit-rate vs IMOEX)\n"
```
(добавить строку в блок «Как спросить» — /track доступен всем; /seed_retro в help не светим.)

- [ ] **Step 3: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/telegram
git commit -m "feat: /seed_retro backfills 60/30-day retro calls and scores them"
```

---

### Task 11: Деплой + E2E-чеклист

- [ ] **Step 1: README — раздел Trust Loop**

Добавить в README.md после «Команды бота»:

```markdown
## Trust Loop (Phase 1.5)

Каждый разбор сохраняется в `calls`; ночной джоб (23:45 МСК) оценивает вызовы
на горизонтах 5/20/60 дней против цены и IMOEX (bullish засчитывается, только
если бумага выросла И обогнала индекс). `/track` показывает hit-rate по ставкам,
средний результат vs IMOEX, бейзлайн и худшие промахи. `/seed_retro` (владелец,
идемпотентно) ретро-сеет разборы по текущим позициям с датой 60/30 дней назад.
```

- [ ] **Step 2: Deploy**

```bash
railway up --service app --ci
```

- [ ] **Step 3: MANUAL — E2E-чеклист**

- [ ] `/ask SBER` → в конце отчёта нет «прошлого мнения» (первый вызов); повторный `/ask SBER` → «🕰 Прошлый разбор (сегодня): …»
- [ ] Владелец: `/ask SBER стоит докупать?` → ответ ссылается на реальную позицию (шт/средняя/вес)
- [ ] Гость (или до /start): позиция в ответ НЕ утекает
- [ ] `/track` до посева → «оценённых пока нет, в очереди N»
- [ ] `/seed_retro` → «посеяно ~2×позиций новых, оценено M» → `/track` показывает hit-rate, бейзлайн, промахи
- [ ] Повторный `/seed_retro` → «посеяно 0 новых, пропущено 2×N существующих» (идемпотентность)
- [ ] В БД: `SELECT count(*) FROM calls` растёт; `SELECT * FROM call_scores LIMIT 5` — вменяемые проценты
- [ ] Логи ночью: `scoring_done scored=N`

- [ ] **Step 4: Финальный коммит + тег**

```bash
git add README.md && git commit -m "docs: trust loop README" && git tag phase-1.5
```

---

## Adversarial review (2026-07-09, мультиагентный: 3 ревьюера × верификация)

19 сырых находок → 9 подтверждено → 5 дефектов исправлено в этой версии плана:
сортировка свечей перед return_between/[-35:] (major); ранжирование «худших промахов»
только по промахам через |excess| (major); /track не врёт «пока нет» при живых 5-дневных
оценках (major); count_unscored не считает NULL-price вызовы (minor); /seed_retro
идемпотентен по (тикер, as-of) вместо одноразового гарда (minor).

## Self-review checklist (выполнен при написании)

- **Coverage разбора:** calls-таблица ✅ (T1-2) · ночной скоринг vs IMOEX ✅ (T3-5) · /track с промахами и бейзлайном ✅ (T8) · позиционный /ask ✅ (T6-7) · consistency-флаг ✅ (T7) · ретро-посев ✅ (T10) · spotlight пишет calls ✅ (T9)
- **Типы согласованы:** `CallRecord`/`ScoredCall` (T2) используются в T4/T5/T7/T8/T10 с теми же полями; `format_analyst_report(prev_note=...)` (T7) соответствует вызову; `save_call(created_at=...)` (T2) используется ретро-посевом (T10); `build_position_note` живёт в ask.py и передаётся строкой в `run_analyst(position_note=...)` (T6)
- **Placeholder scan:** каждый шаг содержит конкретный код/команды; manual-шаги — чеклисты ✅
- **Приватность:** позиция подаётся только когда `asked_by == owner_id`; /seed_retro owner-only; /track общедоступен и не палит объёмы позиций (только тикеры/вердикты) ✅
- **Cost-контроль:** ретро-посев ограничен MAX_POSITIONS×2 вызовами и одноразовый; скоринг LLM не использует ✅
