# Phase 3 «Память и тезисы» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот получает долгосрочную память: тезисы у позиций (авто-генерация для ≥5% портфеля, валидация каждой новостью, автозапуск комитета при инвалидации), position-sync (детект открытий/закрытий с realized return), семантическая память прошлых разборов + «уроки» Reflective Agent (вс 23:00) подмешиваются в промпты комитета; команды `/thesis`, `/insights`, `/history`.

**Architecture:** Embeddings (text-embedding-3-small, 1536d) через новый `Embedder` с учётом расходов; pgvector-колонки на `calls` + новые таблицы `theses`/`insights` (HNSW, cosine); ядро комитета выносится из handler в `committee/runner.py` (переиспользуется handler'ом и Thesis Validator'ом); все LLM-числа по-прежнему считает код (realized return — через существующий `return_between`).

**Tech Stack:** существующий + `pgvector` (python-пакет, SQLAlchemy Vector type). Embeddings — OpenAI text-embedding-3-small (~$0.02/1M токенов, копейки).

**Spec:** `docs/superpowers/specs/2026-06-04-roaring-kittens-design.md` §8.

**Verification model:** тесты в GitHub Actions CI (pgvector-контейнер уже там — HNSW/косинус тестируемы integration-тестами); батчи → push → `gh run watch`; деплой `railway up --service app --ci`.

**Сознательные отклонения от спеки §8:**
1. **Отдельной таблицы `episodes` НЕТ** — эпизодическая память = существующие `calls` (+embedding) и `theses`. Спековский generic event-log — YAGNI: все реальные события уже покрыты этими двумя таблицами.
2. **Drivers/invalidation_triggers — текстом**, не JSONB-массивами: комитет уже выдаёт `thesis`/`invalidation` строками (Proposal), структурирование — когда появится реальная нужда.
3. **Ретро-импорт тезисов заменён живым авто-тезисом**: position-sync ежедневно находит позицию ≥5% без тезиса → генерит тезис (gpt-4o) → уведомляет с кнопкой удаления. Проще onboarding-флоу из спеки и работает постоянно, а не однократно.
4. **Memory retrieval — в комитет** (дебаты + PM), не в одиночный `/ask`: /ask остаётся дешёвым; полный контекст памяти — там, где принимается решение.
5. **Архивация insights по `times_applied`** — не в этой фазе (только счётчик применений); естественный отбор включим, когда уроков станет >20.
6. **Working memory** (state диалога) — не нужна: вся оркестрация одноразовая, LangGraph-state уже есть.

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── ai/
│   ├── embeddings.py       # NEW: Embedder (text-embedding-3-small + usage log)
│   └── ...
├── committee/
│   ├── runner.py           # NEW: run_council_flow — ядро /council (handler и validator)
│   ├── memory.py           # NEW: build_memory_note (похожие разборы + уроки)
│   ├── thesis_gen.py       # NEW: ThesisDraft + генерация авто-тезиса
│   ├── thesis_check.py     # NEW: ThesisCheck + валидация тезиса новостями
│   ├── context.py          # MOD: + memory_note
│   ├── debate.py           # MOD: memory_note в промпт
│   ├── manager.py          # MOD: memory_note в промпт
│   └── render.py           # MOD: + кнопочные тексты не нужны (кнопки в handlers)
├── db/
│   ├── theses.py           # NEW: репозиторий тезисов
│   ├── insights.py         # NEW: репозиторий уроков + vector search
│   ├── calls.py            # MOD: + embedding в save_call, find_similar_calls,
│   │                       #        council_ran_recently, get_ticker_history
│   └── tables.py           # MOD: + theses, insights, calls.embedding (Vector)
├── positions_sync.py       # NEW: diff_positions (pure) + daily job
├── reflection.py           # NEW: Reflective Agent (вс 23:00)
├── scheduler.py            # MOD: + position_sync (08:50) + reflection (вс 23:00)
├── deps.py                 # MOD: + embedder
├── main.py                 # MOD: Embedder wiring
└── telegram/handlers/
    ├── council.py          # MOD: тонкий — через runner; кнопка «📌 Принять тезис»
    ├── thesis.py           # NEW: /thesis /insights /history + callbacks
    └── __init__.py         # MOD: + thesis
db/schema.sql               # MOD: theses, insights, calls.embedding, HNSW-индексы
pyproject.toml              # MOD: + pgvector
tests/
├── test_embedder.py        # NEW
├── test_theses_repo.py     # NEW (integration)
├── test_insights_repo.py   # NEW (integration, vector search)
├── test_similar_calls.py   # NEW (integration)
├── test_memory_note.py     # NEW
├── test_thesis_gen_check.py# NEW
├── test_positions_sync.py  # NEW (pure diff)
├── test_reflection.py      # NEW
├── test_thesis_render.py   # NEW
└── conftest.py             # MOD: truncate theses/insights; фикстура scripted_council_llm
```

---

### Task 1: pgvector-пакет + Embedder

**Files:**
- Modify: `pyproject.toml`, `src/roaring_kittens/deps.py`, `src/roaring_kittens/main.py`
- Create: `src/roaring_kittens/ai/embeddings.py`
- Test: `tests/test_embedder.py`

- [ ] **Step 1: pyproject — добавить в dependencies**

```toml
    "pgvector>=0.2",
```

- [ ] **Step 2: Падающий тест**

```python
# tests/test_embedder.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

from roaring_kittens.ai.embeddings import EMBED_MODEL, Embedder


def _fake_client(vector):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=vector)],
                           usage=SimpleNamespace(prompt_tokens=7, total_tokens=7))
    return SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=resp)))


async def test_embed_returns_vector_and_logs_usage():
    logged = []

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd):
        logged.append((operation, model, input_tokens, output_tokens))

    client = _fake_client([0.1] * 1536)
    emb = Embedder(client=client, usage_logger=fake_log)
    vec = await emb.embed("Сбер растёт", operation="memory_query")
    assert len(vec) == 1536
    assert logged == [("memory_query", EMBED_MODEL, 7, 0)]
    # текст обрезается до 8000 символов
    await emb.embed("x" * 20000, operation="memory_query")
    sent = client.embeddings.create.call_args.kwargs["input"]
    assert len(sent) == 8000
```

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/ai/embeddings.py
from typing import Any

import structlog

from roaring_kittens.ai.llm import UsageLogger
from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
EMBED_COST_PER_1M = 0.02
MAX_INPUT_CHARS = 8000


class Embedder:
    def __init__(self, client: Any, usage_logger: UsageLogger):
        self._client = client
        self._log_usage = usage_logger

    @retry_async(attempts=2, base_delay=2.0)
    async def embed(self, text: str, operation: str) -> list[float]:
        resp = await self._client.embeddings.create(
            model=EMBED_MODEL, input=text[:MAX_INPUT_CHARS])
        tokens = resp.usage.prompt_tokens
        await self._log_usage(operation, EMBED_MODEL, tokens, 0,
                              tokens / 1_000_000 * EMBED_COST_PER_1M)
        return resp.data[0].embedding
```

- [ ] **Step 4: Deps + main wiring**

`deps.py`: добавить поле (после `llm`):

```python
from roaring_kittens.ai.embeddings import Embedder
# в @dataclass Deps:
    embedder: Embedder
```

`main.py` (рядом с созданием LLM; `client = AsyncOpenAI(...)` вынести в переменную и переиспользовать):

```python
from roaring_kittens.ai.embeddings import Embedder

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    usage_logger = make_db_usage_logger(session_factory)
    llm = LLM(client=openai_client, usage_logger=usage_logger)
    embedder = Embedder(client=openai_client, usage_logger=usage_logger)
    deps = Deps(settings=settings, broker=broker, session_factory=session_factory,
                universe=universe, llm=llm, embedder=embedder)
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/roaring_kittens/ai/embeddings.py src/roaring_kittens/deps.py src/roaring_kittens/main.py tests/test_embedder.py
git commit -m "feat: openai embedder with usage logging"
```

---

### Task 2: Схема — theses, insights, calls.embedding

**Files:**
- Modify: `db/schema.sql`, `src/roaring_kittens/db/tables.py`, `tests/conftest.py`

- [ ] **Step 1: schema.sql (перед bot_state)**

```sql
ALTER TABLE calls ADD COLUMN IF NOT EXISTS embedding VECTOR(1536);
CREATE INDEX IF NOT EXISTS idx_calls_embedding ON calls
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS theses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker              VARCHAR(20) NOT NULL,
    figi                VARCHAR(20) NOT NULL,
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at           TIMESTAMPTZ,
    status              VARCHAR(20) NOT NULL DEFAULT 'active',  -- active|closed|invalidated
    thesis              TEXT NOT NULL,
    invalidation        TEXT NOT NULL,
    source              VARCHAR(20) NOT NULL,                   -- 'council' | 'auto'
    confidence          FLOAT,
    entry_price         NUMERIC,
    realized_return_pct NUMERIC,
    close_reason        TEXT
);
CREATE INDEX IF NOT EXISTS idx_theses_status ON theses (status, ticker);

CREATE TABLE IF NOT EXISTS insights (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary       TEXT NOT NULL,
    scope         VARCHAR(50) NOT NULL,     -- ticker|sector|pattern|general
    scope_value   VARCHAR(50),
    confidence    FLOAT NOT NULL,
    embedding     VECTOR(1536),
    times_applied INTEGER NOT NULL DEFAULT 0,
    archived_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_insights_embedding ON insights
    USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 2: tables.py**

Импорты: `from pgvector.sqlalchemy import Vector`. В таблицу `calls` добавить колонку (последней):

```python
    Column("embedding", Vector(1536)),
```

Новые таблицы (перед bot_state):

```python
theses = Table(
    "theses", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("ticker", String(20), nullable=False),
    Column("figi", String(20), nullable=False),
    Column("opened_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("closed_at", TIMESTAMP(timezone=True)),
    Column("status", String(20), nullable=False, server_default=text("'active'")),
    Column("thesis", Text, nullable=False),
    Column("invalidation", Text, nullable=False),
    Column("source", String(20), nullable=False),
    Column("confidence", Float),
    Column("entry_price", Numeric),
    Column("realized_return_pct", Numeric),
    Column("close_reason", Text),
)

insights = Table(
    "insights", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("summary", Text, nullable=False),
    Column("scope", String(50), nullable=False),
    Column("scope_value", String(50)),
    Column("confidence", Float, nullable=False),
    Column("embedding", Vector(1536)),
    Column("times_applied", Integer, nullable=False, server_default=text("0")),
    Column("archived_at", TIMESTAMP(timezone=True)),
)
```

- [ ] **Step 3: conftest truncate**

```python
    await conn.execute(
        "TRUNCATE news_events, usage_log, bot_state, council_runs, call_scores, "
        "calls, theses, insights")
```

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db/tables.py tests/conftest.py
git commit -m "feat: theses and insights tables + calls embedding column"
```

---

### Task 3: Репозиторий тезисов

**Files:**
- Create: `src/roaring_kittens/db/theses.py`
- Test: `tests/test_theses_repo.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_theses_repo.py
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.theses import (
    close_thesis, get_active_theses, get_active_thesis, get_recently_closed, save_thesis,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_save_supersedes_previous_active(db_session_factory):
    async with db_session_factory() as session:
        first = await save_thesis(session, ticker="SBER", figi="F", thesis="старый",
                                  invalidation="i", source="auto", confidence=0.5,
                                  entry_price=Decimal("280"))
        second = await save_thesis(session, ticker="SBER", figi="F", thesis="новый",
                                   invalidation="i2", source="council", confidence=0.7,
                                   entry_price=Decimal("290"))
        await session.commit()
    async with db_session_factory() as session:
        active = await get_active_thesis(session, "SBER")
        assert active is not None and active.id == second.id and active.thesis == "новый"
        all_active = await get_active_theses(session)
        assert [t.id for t in all_active] == [second.id]  # старый закрыт как superseded


async def test_close_thesis_and_recently_closed(db_session_factory):
    async with db_session_factory() as session:
        t = await save_thesis(session, ticker="GAZP", figi="F2", thesis="t",
                              invalidation="i", source="auto", confidence=0.6,
                              entry_price=None)
        await session.commit()
    async with db_session_factory() as session:
        await close_thesis(session, t.id, status="closed",
                           realized_return_pct=Decimal("4.2"),
                           close_reason="позиция закрыта")
        await session.commit()
        assert await get_active_thesis(session, "GAZP") is None
        recent = await get_recently_closed(session, days=7)
        assert len(recent) == 1 and recent[0].realized_return_pct == Decimal("4.2")
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/theses.py
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID as UUIDType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import theses


@dataclass(frozen=True)
class ThesisRecord:
    id: UUIDType
    ticker: str
    figi: str
    opened_at: datetime
    closed_at: datetime | None
    status: str
    thesis: str
    invalidation: str
    source: str
    confidence: float | None
    entry_price: Decimal | None
    realized_return_pct: Decimal | None
    close_reason: str | None


def _row(r) -> ThesisRecord:
    return ThesisRecord(id=r.id, ticker=r.ticker, figi=r.figi, opened_at=r.opened_at,
                        closed_at=r.closed_at, status=r.status, thesis=r.thesis,
                        invalidation=r.invalidation, source=r.source,
                        confidence=r.confidence, entry_price=r.entry_price,
                        realized_return_pct=r.realized_return_pct,
                        close_reason=r.close_reason)


async def save_thesis(session: AsyncSession, *, ticker: str, figi: str, thesis: str,
                      invalidation: str, source: str, confidence: float | None,
                      entry_price: Decimal | None) -> ThesisRecord:
    """Один активный тезис на тикер: прежний закрывается как superseded."""
    await session.execute(
        update(theses)
        .where(theses.c.ticker == ticker, theses.c.status == "active")
        .values(status="closed", closed_at=datetime.now(tz=timezone.utc),
                close_reason="superseded"))
    result = await session.execute(
        theses.insert().values(ticker=ticker, figi=figi, thesis=thesis,
                               invalidation=invalidation, source=source,
                               confidence=confidence, entry_price=entry_price)
        .returning(theses))
    return _row(result.first())


async def get_active_thesis(session: AsyncSession, ticker: str) -> ThesisRecord | None:
    row = (await session.execute(
        select(theses).where(theses.c.ticker == ticker,
                             theses.c.status == "active").limit(1))).first()
    return _row(row) if row else None


async def get_active_theses(session: AsyncSession) -> list[ThesisRecord]:
    rows = (await session.execute(
        select(theses).where(theses.c.status == "active")
        .order_by(theses.c.opened_at))).fetchall()
    return [_row(r) for r in rows]


async def close_thesis(session: AsyncSession, thesis_id: UUIDType, *, status: str,
                       realized_return_pct: Decimal | None,
                       close_reason: str) -> None:
    await session.execute(
        update(theses).where(theses.c.id == thesis_id)
        .values(status=status, closed_at=datetime.now(tz=timezone.utc),
                realized_return_pct=realized_return_pct, close_reason=close_reason))


async def get_recently_closed(session: AsyncSession, days: int = 7) -> list[ThesisRecord]:
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = (await session.execute(
        select(theses).where(theses.c.status != "active",
                             theses.c.closed_at >= since))).fetchall()
    return [_row(r) for r in rows]
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/db/theses.py tests/test_theses_repo.py
git commit -m "feat: theses repository with supersede semantics"
```

---

### Task 4: Репозиторий insights + vector search

**Files:**
- Create: `src/roaring_kittens/db/insights.py`
- Test: `tests/test_insights_repo.py`

- [ ] **Step 1: Падающий тест (косинус реально работает в CI-pgvector)**

```python
# tests/test_insights_repo.py
import os

import pytest

from roaring_kittens.db.insights import (
    bump_times_applied, list_active_insights, save_insight, top_insights_by_similarity,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


def _vec(direction: int) -> list[float]:
    v = [0.0] * 1536
    v[direction] = 1.0
    return v


async def test_similarity_orders_and_filters(db_session_factory):
    async with db_session_factory() as session:
        near = await save_insight(session, summary="банки под дивы работают",
                                  scope="pattern", scope_value="banks_divs",
                                  confidence=0.8, embedding=_vec(0))
        far = await save_insight(session, summary="металлурги слабы",
                                 scope="sector", scope_value="metals",
                                 confidence=0.9, embedding=_vec(1))
        weak = await save_insight(session, summary="слабый урок",
                                  scope="general", scope_value=None,
                                  confidence=0.2, embedding=_vec(0))
        await session.commit()
    async with db_session_factory() as session:
        top = await top_insights_by_similarity(session, _vec(0), k=2, min_confidence=0.5)
        assert [i.id for i in top] == [near.id, far.id]  # weak отфильтрован по confidence
        await bump_times_applied(session, [near.id])
        await session.commit()
        active = await list_active_insights(session)
        bumped = next(i for i in active if i.id == near.id)
        assert bumped.times_applied == 1
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/db/insights.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import insights


@dataclass(frozen=True)
class InsightRecord:
    id: UUIDType
    created_at: datetime
    summary: str
    scope: str
    scope_value: str | None
    confidence: float
    times_applied: int


def _row(r) -> InsightRecord:
    return InsightRecord(id=r.id, created_at=r.created_at, summary=r.summary,
                         scope=r.scope, scope_value=r.scope_value,
                         confidence=r.confidence, times_applied=r.times_applied)


async def save_insight(session: AsyncSession, *, summary: str, scope: str,
                       scope_value: str | None, confidence: float,
                       embedding: list[float] | None) -> InsightRecord:
    result = await session.execute(
        insights.insert().values(summary=summary, scope=scope, scope_value=scope_value,
                                 confidence=confidence, embedding=embedding)
        .returning(insights))
    return _row(result.first())


async def top_insights_by_similarity(session: AsyncSession, embedding: list[float],
                                     k: int = 3,
                                     min_confidence: float = 0.5) -> list[InsightRecord]:
    rows = (await session.execute(
        select(insights)
        .where(insights.c.archived_at.is_(None),
               insights.c.confidence >= min_confidence,
               insights.c.embedding.isnot(None))
        .order_by(insights.c.embedding.cosine_distance(embedding))
        .limit(k))).fetchall()
    return [_row(r) for r in rows]


async def bump_times_applied(session: AsyncSession, ids: list[UUIDType]) -> None:
    if not ids:
        return
    await session.execute(
        update(insights).where(insights.c.id.in_(ids))
        .values(times_applied=insights.c.times_applied + 1))


async def list_active_insights(session: AsyncSession) -> list[InsightRecord]:
    rows = (await session.execute(
        select(insights).where(insights.c.archived_at.is_(None))
        .order_by(insights.c.created_at.desc()))).fetchall()
    return [_row(r) for r in rows]
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/db/insights.py tests/test_insights_repo.py
git commit -m "feat: insights repository with cosine similarity search"
```

---

### Task 5: Embedding у calls + похожие разборы + история

**Files:**
- Modify: `src/roaring_kittens/db/calls.py`
- Test: `tests/test_similar_calls.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_similar_calls.py
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from roaring_kittens.db.calls import (
    council_ran_recently, find_similar_calls, get_ticker_history, save_call, save_score,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

NOW = datetime.now(tz=timezone.utc)


def _vec(direction: int) -> list[float]:
    v = [0.0] * 1536
    v[direction] = 1.0
    return v


async def _save(session, *, ticker="SBER", stance="bullish", embedding=None,
                source="ask", created_at=None):
    return await save_call(
        session, asked_by=1, ticker=ticker, figi="F", source=source, question=None,
        stance=stance, confidence=0.6, summary=f"{ticker} разбор",
        price_at_call=Decimal("100"), news_urls=[], created_at=created_at,
        embedding=embedding)


async def test_find_similar_returns_nearest_with_score(db_session_factory):
    async with db_session_factory() as session:
        near = await _save(session, ticker="GAZP", embedding=_vec(0))
        await _save(session, ticker="LKOH", embedding=_vec(1))
        await _save(session, ticker="NONE", embedding=None)  # без эмбеддинга — вне поиска
        await save_score(session, near, 20, Decimal("5.0"), Decimal("1.0"), "hit")
        await session.commit()
    async with db_session_factory() as session:
        similar = await find_similar_calls(session, _vec(0), k=2)
        assert similar[0].ticker == "GAZP"
        assert similar[0].score_20d is not None and similar[0].score_20d.verdict == "hit"
        assert similar[1].ticker == "LKOH" and similar[1].score_20d is None


async def test_council_ran_recently_and_history(db_session_factory):
    async with db_session_factory() as session:
        c = await _save(session, ticker="SBER", source="council")
        await _save(session, ticker="SBER", source="ask",
                    created_at=NOW - timedelta(days=2))
        await session.commit()
    async with db_session_factory() as session:
        assert await council_ran_recently(session, "SBER", hours=24) is True
        assert await council_ran_recently(session, "GAZP", hours=24) is False
        history = await get_ticker_history(session, "SBER", limit=5)
        assert len(history) == 2 and history[0].source == "council"  # свежие первыми
```

- [ ] **Step 2: Реализовать (дописать в db/calls.py)**

`save_call` — новый kwarg `embedding: list[float] | None = None`, в values добавить `embedding=embedding`.

Новые типы/функции:

```python
# дописать в src/roaring_kittens/db/calls.py
@dataclass(frozen=True)
class SimilarCall:
    ticker: str
    stance: str
    created_at: datetime
    summary: str
    score_20d: ScoredCall | None


@dataclass(frozen=True)
class HistoryItem:
    created_at: datetime
    source: str
    stance: str
    confidence: float
    summary: str
    score_20d: ScoredCall | None


def _score_row_to_scored(call_row, s_horizon, s_stock, s_imoex, s_verdict) -> ScoredCall | None:
    if s_horizon is None:
        return None
    return ScoredCall(ticker=call_row.ticker, stance=call_row.stance,
                      created_at=call_row.created_at, source=call_row.source,
                      horizon_days=s_horizon, stock_return_pct=s_stock,
                      imoex_return_pct=s_imoex, verdict=s_verdict)


def _calls_with_score20():
    from sqlalchemy import and_
    j = calls.outerjoin(call_scores, and_(call_scores.c.call_id == calls.c.id,
                                          call_scores.c.horizon_days == 20))
    return j


async def find_similar_calls(session: AsyncSession, embedding: list[float],
                             k: int = 3) -> list[SimilarCall]:
    j = _calls_with_score20()
    rows = (await session.execute(
        select(calls, call_scores.c.horizon_days, call_scores.c.stock_return_pct,
               call_scores.c.imoex_return_pct, call_scores.c.verdict)
        .select_from(j)
        .where(calls.c.embedding.isnot(None))
        .order_by(calls.c.embedding.cosine_distance(embedding))
        .limit(k))).fetchall()
    out = []
    for r in rows:
        score = _score_row_to_scored(r, r.horizon_days, r.stock_return_pct,
                                     r.imoex_return_pct, r.verdict)
        out.append(SimilarCall(ticker=r.ticker, stance=r.stance,
                               created_at=r.created_at, summary=r.summary,
                               score_20d=score))
    return out


async def council_ran_recently(session: AsyncSession, ticker: str,
                               hours: int = 24) -> bool:
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    row = (await session.execute(
        select(calls.c.id).where(calls.c.ticker == ticker,
                                 calls.c.source == "council",
                                 calls.c.created_at >= since).limit(1))).first()
    return row is not None


async def get_ticker_history(session: AsyncSession, ticker: str,
                             limit: int = 5) -> list[HistoryItem]:
    j = _calls_with_score20()
    rows = (await session.execute(
        select(calls, call_scores.c.horizon_days, call_scores.c.stock_return_pct,
               call_scores.c.imoex_return_pct, call_scores.c.verdict)
        .select_from(j)
        .where(calls.c.ticker == ticker)
        .order_by(calls.c.created_at.desc())
        .limit(limit))).fetchall()
    return [HistoryItem(created_at=r.created_at, source=r.source, stance=r.stance,
                        confidence=r.confidence, summary=r.summary,
                        score_20d=_score_row_to_scored(r, r.horizon_days,
                                                       r.stock_return_pct,
                                                       r.imoex_return_pct, r.verdict))
            for r in rows]
```

- [ ] **Step 3: Best-effort embedding при записи разборов**

В `telegram/handlers/ask.py` (`_analyze_and_edit`, блок записи call): перед `save_call` добавить

```python
        embedding = None
        try:
            embedding = await deps.embedder.embed(
                f"{instrument.ticker} {report.stance}: {report.summary}",
                operation="embed_call")
        except Exception as exc:
            log.warning("embed_call_failed", error=str(exc))
```

и передать `embedding=embedding` в `save_call`. Аналогично в `digest/morning.py` (`build_spotlight`) и `telegram/handlers/seed.py` — тем же паттерном (текст: тикер + stance + summary). В council запись перенесётся в runner (Task 7) — embedding добавить там.

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/db/calls.py src/roaring_kittens/telegram/handlers/ask.py src/roaring_kittens/telegram/handlers/seed.py src/roaring_kittens/digest/morning.py tests/test_similar_calls.py
git commit -m "feat: call embeddings, similarity search, history and council-recency queries"
```

---

### Task 6: Memory note для комитета

**Files:**
- Create: `src/roaring_kittens/committee/memory.py`
- Modify: `src/roaring_kittens/committee/context.py`, `src/roaring_kittens/committee/debate.py`, `src/roaring_kittens/committee/manager.py`, `tests/conftest.py` (council_ctx: + memory_note=None)
- Test: `tests/test_memory_note.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_memory_note.py
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import roaring_kittens.committee.memory as mem_mod
from roaring_kittens.committee.memory import MEMORY_CHAR_CAP, build_memory_note
from roaring_kittens.db.calls import ScoredCall, SimilarCall
from roaring_kittens.db.insights import InsightRecord

NOW = datetime.now(tz=timezone.utc)


class FakeSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


class FakeEmbedder:
    async def embed(self, text, operation):
        return [0.0] * 1536


def _similar(ticker, verdict=None):
    score = None
    if verdict:
        score = ScoredCall(ticker=ticker, stance="bullish", created_at=NOW, source="ask",
                           horizon_days=20, stock_return_pct=Decimal("5"),
                           imoex_return_pct=Decimal("1"), verdict=verdict)
    return SimilarCall(ticker=ticker, stance="bullish", created_at=NOW,
                       summary="рост на отчёте", score_20d=score)


async def test_memory_note_contains_similar_and_insights(monkeypatch):
    async def fake_similar(session, emb, k=3):
        return [_similar("GAZP", "hit")]

    async def fake_insights(session, emb, k=3, min_confidence=0.5):
        return [InsightRecord(id=uuid4(), created_at=NOW, summary="банки под дивы работают",
                              scope="pattern", scope_value="x", confidence=0.8,
                              times_applied=0)]

    async def fake_bump(session, ids):
        fake_bump.called = ids
    fake_bump.called = None

    monkeypatch.setattr(mem_mod, "find_similar_calls", fake_similar)
    monkeypatch.setattr(mem_mod, "top_insights_by_similarity", fake_insights)
    monkeypatch.setattr(mem_mod, "bump_times_applied", fake_bump)
    deps = SimpleNamespace(embedder=FakeEmbedder(), session_factory=lambda: FakeSession())

    note = await build_memory_note(deps, "SBER", "SBER: рост на объёме")
    assert "GAZP" in note and "hit" in note
    assert "банки под дивы" in note
    assert len(note) <= MEMORY_CHAR_CAP
    assert fake_bump.called is not None  # применённые уроки посчитаны


async def test_memory_note_none_when_empty(monkeypatch):
    async def none_similar(session, emb, k=3):
        return []

    async def none_insights(session, emb, k=3, min_confidence=0.5):
        return []

    monkeypatch.setattr(mem_mod, "find_similar_calls", none_similar)
    monkeypatch.setattr(mem_mod, "top_insights_by_similarity", none_insights)
    deps = SimpleNamespace(embedder=FakeEmbedder(), session_factory=lambda: FakeSession())
    assert await build_memory_note(deps, "SBER", "ситуация") is None
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/memory.py
"""Память комитета: похожие прошлые разборы (с исходом) + применимые уроки."""
import structlog

from roaring_kittens.db.calls import find_similar_calls
from roaring_kittens.db.insights import bump_times_applied, top_insights_by_similarity

log = structlog.get_logger()

MEMORY_CHAR_CAP = 4000  # ~1000-1500 токенов


async def build_memory_note(deps, ticker: str, situation_text: str) -> str | None:
    try:
        emb = await deps.embedder.embed(f"{ticker}: {situation_text}",
                                        operation="memory_query")
    except Exception as exc:
        log.warning("memory_embed_failed", error=str(exc))
        return None
    async with deps.session_factory() as session:
        similar = await find_similar_calls(session, emb, k=3)
        applicable = await top_insights_by_similarity(session, emb, k=3,
                                                      min_confidence=0.5)
        if applicable:
            await bump_times_applied(session, [i.id for i in applicable])
            await session.commit()
    if not similar and not applicable:
        return None
    lines = ["Память бота (прошлый опыт, учитывай критично):"]
    if similar:
        lines.append("Похожие прошлые разборы:")
        for s in similar:
            outcome = ""
            if s.score_20d:
                sign = "+" if s.score_20d.excess_pp >= 0 else "−"
                outcome = (f" → 20д: {sign}{abs(s.score_20d.excess_pp)} пп vs IMOEX "
                           f"({s.score_20d.verdict})")
            lines.append(f"- {s.created_at:%d.%m} {s.ticker} {s.stance}: "
                         f"{s.summary}{outcome}")
    if applicable:
        lines.append("Выученные уроки:")
        for i in applicable:
            lines.append(f"- {i.summary} (уверенность {round(i.confidence*100)}%)")
    return "\n".join(lines)[:MEMORY_CHAR_CAP]
```

- [ ] **Step 3: Прошивка в контекст и промпты**

`context.py`: `CouncilContext` — новое поле `memory_note: str | None = None`... dataclass без default в конце? Поля с default должны идти последними — добавить `memory_note: str | None` ПОСЛЕДНИМ полем с default `None`:

```python
    memory_note: str | None = None
```

В `build_council_context` перед `return`:

```python
    situation = f"{tech.as_text() if tech else 'нет техники'}; " + \
                "; ".join(n.headline for n in facts[:5])
    memory_note = await build_memory_note(deps, instrument.ticker, situation)
```

(импорт `from roaring_kittens.committee.memory import build_memory_note`; в return добавить `memory_note=memory_note`)

`debate.py` (`build_debate_user`, после prev_call_note) и `manager.py` (`build_manager_user`, там же):

```python
    if ctx.memory_note:
        parts.append(f"\n{ctx.memory_note}")
```

`tests/conftest.py` фикстура `council_ctx`: добавить `memory_note=None` в конструктор.

Тест контекста (`tests/test_council_context.py`): в `test_build_context_...` замокать память:

```python
    async def fake_memory(deps, ticker, situation):
        return None
    monkeypatch.setattr(ctx_mod, "build_memory_note", fake_memory)
```

и assert `ctx.memory_note is None`.

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/committee tests/test_memory_note.py tests/conftest.py tests/test_council_context.py
git commit -m "feat: semantic memory note injected into debate and manager prompts"
```

---

### Task 7: Runner — ядро /council для переиспользования

**Files:**
- Create: `src/roaring_kittens/committee/runner.py`
- Modify: `src/roaring_kittens/telegram/handlers/council.py` (тонкий)
- Test: `tests/test_council_runner.py`, фикстура `scripted_council_llm` в `tests/conftest.py`

- [ ] **Step 1: Фикстура ScriptedLLM в conftest (переносим класс из test_council_graph, там заменить на фикстуру)**

```python
# tests/conftest.py — в конец
@pytest.fixture
def scripted_council_llm():
    """LLM-сценарий комитета: bear сдаётся на 2-м раунде, PM=wait, Risk=approved."""
    from roaring_kittens.committee.schemas import (
        DebateTurn, Proposal, RiskReview, SpecialistView,
    )

    class ScriptedLLM:
        def __init__(self):
            self.ops = []
            self.bear_turns = 0

        async def parse(self, *, model, operation, messages, schema, temperature=None):
            self.ops.append(operation)
            if operation.startswith("council_debate_bull"):
                return DebateTurn(argument="за", rebuttal_of="-", position_after="bullish")
            if operation.startswith("council_debate_bear"):
                self.bear_turns += 1
                pos = "bearish" if self.bear_turns == 1 else "bullish"
                return DebateTurn(argument="против", rebuttal_of="-", position_after=pos)
            if operation == "council_manager":
                return Proposal(action="wait", stance="neutral", rationale="r",
                                thesis="t", invalidation="i", confidence=0.55)
            if operation == "council_risk":
                return RiskReview(approved=True, veto_reason=None, notes=[])
            return SpecialistView(role="news", stance="neutral", summary="s",
                                  key_points=["k"], confidence=0.5)

    return ScriptedLLM()
```

В `tests/test_council_graph.py` удалить локальный класс, использовать фикстуру:
`async def test_graph_runs_end_to_end_with_early_convergence(council_ctx, scripted_council_llm):`
и `llm = scripted_council_llm`.

- [ ] **Step 2: Падающий тест runner'а**

```python
# tests/test_council_runner.py
from types import SimpleNamespace

import roaring_kittens.committee.runner as runner_mod
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.universe.universe import Instrument

INSTR = Instrument(ticker="SBER", figi="F", name="Сбер", aliases=frozenset())


async def test_runner_returns_outcome_and_persists(council_ctx, scripted_council_llm,
                                                   monkeypatch):
    stages = []
    saved = {}

    async def fake_persist(deps, instrument, asked_by, ctx, state):
        saved["state"] = state
        return ("call-id", "run-id")

    monkeypatch.setattr(runner_mod, "_persist_council", fake_persist)
    deps = SimpleNamespace(llm=scripted_council_llm)

    async def on_stage(text):
        stages.append(text)

    outcome = await run_council_flow(deps, INSTR, asked_by=42, ctx=council_ctx,
                                     on_stage=on_stage)
    assert outcome.proposal.action == "wait" and outcome.risk.approved
    assert outcome.call_id == "call-id" and outcome.run_id == "run-id"
    assert len(outcome.state["debate"]) == 4
    assert any("Bull vs Bear" in s for s in stages)   # стадии анонсировались
    assert saved["state"]["proposal"].action == "wait"
```

- [ ] **Step 3: Реализовать runner + утончить handler**

```python
# src/roaring_kittens/committee/runner.py
"""Ядро /council: прогон графа + персист. Используется handler'ом и Thesis Validator'ом."""
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable
from uuid import UUID as UUIDType

import structlog

from roaring_kittens.committee.context import CouncilContext, build_council_context
from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged
from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.schemas import Proposal, RiskReview
from roaring_kittens.db.calls import save_call
from roaring_kittens.db.council import save_council_run
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()

OnStage = Callable[[str], Awaitable[None]]


@dataclass
class CouncilOutcome:
    state: dict
    proposal: Proposal
    risk: RiskReview
    call_id: UUIDType | None
    run_id: UUIDType | None


def next_stage_text(node: str, state: dict, ticker: str) -> str | None:
    """astream(updates) стреляет ПОСЛЕ узла — анонсируем СЛЕДУЮЩУЮ стадию."""
    if node == "specialists":
        return f"⚔️ {ticker}: аналитики высказались — дебаты Bull vs Bear…"
    if node == "bear":
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return f"👔 {ticker}: дебаты завершены — Portfolio Manager взвешивает…"
        return f"⚔️ {ticker}: дебаты, раунд {state['round'] + 1}…"
    if node == "manager":
        return f"🛡 {ticker}: Risk Manager проверяет…"
    return None


async def _persist_council(deps, instrument: Instrument, asked_by: int,
                           ctx: CouncilContext, state: dict):
    """Одобренный вердикт → calls (+embedding); транскрипт (с meta) → council_runs."""
    proposal, risk = state["proposal"], state["risk"]
    call_id = run_id = None
    embedding = None
    try:
        embedding = await deps.embedder.embed(
            f"{instrument.ticker} {proposal.stance}: {proposal.rationale}",
            operation="embed_call")
    except Exception as exc:
        log.warning("embed_call_failed", error=str(exc))
    async with deps.session_factory() as session:
        if risk.approved:
            call_id = await save_call(
                session, asked_by=asked_by, ticker=instrument.ticker,
                figi=instrument.figi, source="council", question=None,
                stance=proposal.stance, confidence=proposal.confidence,
                summary=proposal.rationale,
                price_at_call=ctx.tech.last_close if ctx.tech else None,
                news_urls=[n.url for n in ctx.news_facts + ctx.crowd_posts],
                embedding=embedding)
        transcript = {
            "meta": {"ticker": instrument.ticker, "figi": instrument.figi,
                     "price_at_call": str(ctx.tech.last_close) if ctx.tech else None},
            "views": [v.model_dump() for v in state["views"]],
            "debate": state["debate"],
            "proposal": proposal.model_dump(),
            "risk": risk.model_dump(),
        }
        run_id = await save_council_run(session, ticker=instrument.ticker,
                                        asked_by=asked_by, transcript=transcript,
                                        call_id=call_id)
        await session.commit()
    return call_id, run_id


async def run_council_flow(deps, instrument: Instrument, asked_by: int,
                           ctx: CouncilContext | None = None,
                           on_stage: OnStage | None = None) -> CouncilOutcome:
    if ctx is None:
        ctx = await build_council_context(deps, instrument, asked_by,
                                          today=date.today())
    graph = build_council_graph(deps.llm)
    state: dict = {"ctx": ctx}
    async for chunk in graph.astream(state, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if on_stage:
                stage = next_stage_text(node, state, instrument.ticker)
                if stage:
                    try:
                        await on_stage(stage)
                    except Exception:
                        pass
    call_id = run_id = None
    try:  # персист не должен ронять ответ
        call_id, run_id = await _persist_council(deps, instrument, asked_by, ctx, state)
    except Exception as exc:
        log.error("council_persist_failed", ticker=instrument.ticker, error=str(exc))
    return CouncilOutcome(state=state, proposal=state["proposal"], risk=state["risk"],
                          call_id=call_id, run_id=run_id)
```

`telegram/handlers/council.py` — `cmd_council` становится тонким (гейты и USAGE без изменений; `_next_stage_text` и старый персист-блок удалить; импорты почистить: убрать build_council_context/build_council_graph/save_call/save_council_run/date, добавить runner):

```python
from roaring_kittens.committee.runner import run_council_flow

    progress = await message.answer(
        f"🏛 Собираю комитет по {instrument.ticker}… (4 аналитика изучают данные)")
    try:
        async def on_stage(text: str) -> None:
            await progress.edit_text(text)

        outcome = await run_council_flow(deps, instrument, message.from_user.id,
                                         on_stage=on_stage)
    except Exception as exc:
        log.error("council_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Комитет по {instrument.ticker} сорвался — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/council {instrument.ticker}</code>")
        return

    keyboard = None
    if outcome.run_id is not None:
        buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                         callback_data=f"proto:{outcome.run_id}")]]
        if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
            buttons.append([InlineKeyboardButton(
                text="📌 Принять тезис", callback_data=f"thesis_save:{outcome.run_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await progress.edit_text(
        format_council_verdict(instrument.ticker, outcome.state["views"],
                               outcome.state["debate"], outcome.proposal, outcome.risk),
        reply_markup=keyboard)
```

- [ ] **Step 4: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/committee/runner.py src/roaring_kittens/telegram/handlers/council.py tests/conftest.py tests/test_council_runner.py tests/test_council_graph.py
git commit -m "refactor: extract council runner (reused by handler and thesis validator)"
```

---

### Task 8: Генерация и проверка тезисов (LLM-обвязка)

**Files:**
- Create: `src/roaring_kittens/committee/thesis_gen.py`, `src/roaring_kittens/committee/thesis_check.py`
- Test: `tests/test_thesis_gen_check.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_thesis_gen_check.py
from datetime import datetime, timezone

from roaring_kittens.committee.thesis_check import ThesisCheck, run_thesis_check
from roaring_kittens.committee.thesis_gen import ThesisDraft, run_thesis_draft
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.news.models import NewsItem


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_thesis_draft_op_and_model(council_ctx):
    llm = FakeLLM(ThesisDraft(thesis="дивидендная история",
                              invalidation="отмена дивидендов", confidence=0.6))
    draft = await run_thesis_draft(llm, council_ctx)
    assert "дивидендная" in draft.thesis
    assert llm.calls == [("thesis_draft", "gpt-4o")]


def _thesis():
    return ThesisRecord(id=None, ticker="SBER", figi="F",
                        opened_at=datetime.now(tz=timezone.utc), closed_at=None,
                        status="active", thesis="рост под дивиденды",
                        invalidation="дивы отменены или ниже 20 ₽", source="auto",
                        confidence=0.6, entry_price=None, realized_return_pct=None,
                        close_reason=None)


async def test_thesis_check_uses_mini_and_returns_status():
    llm = FakeLLM(ThesisCheck(status="invalidated", reasoning_short="дивы отменили"))
    news = [NewsItem(source="rbc", url="https://x/1",
                     headline="Сбер отменил дивиденды",
                     body=None, published_at=datetime.now(tz=timezone.utc),
                     tickers=["SBER"])]
    check = await run_thesis_check(llm, _thesis(), news)
    assert check.status == "invalidated"
    assert llm.calls == [("thesis_check", "gpt-4o-mini")]
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/thesis_gen.py
"""Авто-тезис для позиции без тезиса (position-sync). Дешёвый одиночный вызов."""
from pydantic import BaseModel, Field

from roaring_kittens.committee.context import CouncilContext

THESIS_MODEL = "gpt-4o"

THESIS_SYSTEM = """Ты — аналитик. У пользователя уже ЕСТЬ эта бумага в портфеле.
Сформулируй наиболее правдоподобный ТЕЗИС удержания позиции (зачем её держать)
и КОНКРЕТНЫЙ проверяемый триггер инвалидации (при каком событии/уровне тезис ломается).
Опирайся только на данные. По-русски, кратко."""


class ThesisDraft(BaseModel):
    thesis: str = Field(description="однострочный тезис удержания")
    invalidation: str = Field(description="конкретный проверяемый триггер поломки тезиса")
    confidence: float = Field(ge=0, le=1)


async def run_thesis_draft(llm, ctx: CouncilContext) -> ThesisDraft:
    user = (f"Тикер: {ctx.ticker}\n"
            f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}\n"
            f"{ctx.dividend_summary}\n"
            f"{ctx.position_note or ''}")
    return await llm.parse(model=THESIS_MODEL, operation="thesis_draft",
                           messages=[{"role": "system", "content": THESIS_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ThesisDraft)
```

```python
# src/roaring_kittens/committee/thesis_check.py
"""Валидация тезиса свежими новостями (gpt-4o-mini, копейки)."""
from typing import Literal

from pydantic import BaseModel, Field

from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.news.models import NewsItem

CHECK_MODEL = "gpt-4o-mini"

CHECK_SYSTEM = """Ты проверяешь, не сломали ли свежие новости инвестиционный тезис.
Отвечай строго по предоставленному. invalidated — только если новость ПРЯМО срабатывает
триггер инвалидации или очевидно рушит тезис. weakened — если новость заметно против
тезиса, но триггер не сработал. Иначе still_valid. По-русски, кратко."""


class ThesisCheck(BaseModel):
    status: Literal["still_valid", "weakened", "invalidated"]
    reasoning_short: str = Field(description="одно предложение почему")


async def run_thesis_check(llm, thesis: ThesisRecord,
                           news: list[NewsItem]) -> ThesisCheck:
    headlines = "\n".join(f"- {n.headline}" for n in news[:8])
    user = (f"Тикер: {thesis.ticker}\n"
            f"Тезис: {thesis.thesis}\n"
            f"Триггер инвалидации: {thesis.invalidation}\n\n"
            f"Свежие новости:\n{headlines}")
    return await llm.parse(model=CHECK_MODEL, operation="thesis_check",
                           messages=[{"role": "system", "content": CHECK_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ThesisCheck)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/thesis_gen.py src/roaring_kittens/committee/thesis_check.py tests/test_thesis_gen_check.py
git commit -m "feat: thesis draft generator and news-driven thesis validator"
```

---

### Task 9: Position-sync (pure diff + daily job)

**Files:**
- Create: `src/roaring_kittens/positions_sync.py`
- Modify: `src/roaring_kittens/scheduler.py`
- Test: `tests/test_positions_sync.py`

- [ ] **Step 1: Падающий тест (pure)**

```python
# tests/test_positions_sync.py
from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.positions_sync import diff_positions


def _pos(ticker, qty="100", cur="100"):
    return Position(ticker=ticker, name=ticker, figi=f"F-{ticker}",
                    quantity=Decimal(qty), avg_price=Decimal("90"),
                    current_price=Decimal(cur), pnl_pct=Decimal("11.1"))


def _thesis(ticker):
    return ThesisRecord(id=ticker, ticker=ticker, figi=f"F-{ticker}",
                        opened_at=datetime.now(tz=timezone.utc), closed_at=None,
                        status="active", thesis="t", invalidation="i", source="auto",
                        confidence=0.5, entry_price=None, realized_return_pct=None,
                        close_reason=None)


def test_diff_detects_closures_and_new_big_positions():
    # Портфель 100k: SBER 60k (60%), LKOH 40k (40%)... и тезис по проданному GAZP
    snap = PortfolioSnapshot(total_value=Decimal("100000"),
                             positions=[_pos("SBER", qty="600"),
                                        _pos("LKOH", qty="400")])
    actions = diff_positions(snap, [_thesis("GAZP"), _thesis("SBER")],
                             min_weight_pct=Decimal("5"))
    assert [t.ticker for t in actions.to_close] == ["GAZP"]   # позиции нет — закрыть
    assert [p.ticker for p in actions.to_draft] == ["LKOH"]   # ≥5% и без тезиса


def test_diff_skips_small_positions_and_empty_snapshot():
    snap = PortfolioSnapshot(total_value=Decimal("100000"),
                             positions=[_pos("PLZL", qty="1")])  # 100/100k = 0.1%
    actions = diff_positions(snap, [], min_weight_pct=Decimal("5"))
    assert actions.to_draft == [] and actions.to_close == []
    empty = PortfolioSnapshot(total_value=Decimal("0"), positions=[])
    actions = diff_positions(empty, [_thesis("SBER")], min_weight_pct=Decimal("5"))
    assert [t.ticker for t in actions.to_close] == ["SBER"]
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/positions_sync.py
"""Ежедневная сверка портфеля с тезисами: закрытия и новые крупные позиции."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog

from roaring_kittens.broker.benchmark import return_between
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.broker.position_note import position_weight_pct
from roaring_kittens.committee.context import build_council_context
from roaring_kittens.committee.thesis_gen import run_thesis_draft
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import ThesisRecord, close_thesis, get_active_theses, save_thesis
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()

MIN_THESIS_WEIGHT_PP = Decimal("5")


@dataclass(frozen=True)
class SyncActions:
    to_close: list[ThesisRecord]   # активный тезис, позиции больше нет
    to_draft: list[Position]       # позиция ≥ порога без активного тезиса


def diff_positions(snap: PortfolioSnapshot, active: list[ThesisRecord],
                   min_weight_pct: Decimal = MIN_THESIS_WEIGHT_PP) -> SyncActions:
    held = {p.ticker for p in snap.positions}
    with_thesis = {t.ticker for t in active}
    to_close = [t for t in active if t.ticker not in held]
    to_draft = [p for p in snap.positions
                if p.ticker not in with_thesis
                and (position_weight_pct(snap, p.ticker) or Decimal("0")) >= min_weight_pct]
    return SyncActions(to_close=to_close, to_draft=to_draft)


async def _realized_return(deps, thesis: ThesisRecord) -> Decimal | None:
    try:
        lookback = (datetime.now(tz=timezone.utc) - thesis.opened_at).days + 15
        candles = await deps.broker.get_daily_candles(thesis.figi, days=max(lookback, 40))
    except Exception as exc:
        log.warning("sync_candles_failed", ticker=thesis.ticker, error=str(exc))
        return None
    closes = sorted((c.day, c.close) for c in candles)
    start = thesis.opened_at.date()
    end = datetime.now(tz=timezone.utc).date()
    return return_between(closes, start, end)


async def sync_positions(deps, bot) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    try:
        snap = await deps.broker.get_portfolio()
    except Exception as exc:
        log.error("sync_portfolio_failed", error=str(exc))
        return
    async with deps.session_factory() as session:
        active = await get_active_theses(session)
    actions = diff_positions(snap, active)

    for thesis in actions.to_close:
        ret = await _realized_return(deps, thesis)
        async with deps.session_factory() as session:
            await close_thesis(session, thesis.id, status="closed",
                               realized_return_pct=ret,
                               close_reason="позиция закрыта")
            await session.commit()
        sign = "" if ret is None else (f", результат {'+' if ret >= 0 else '−'}{abs(ret)}%"
                                       " за время тезиса")
        await bot.send_message(owner_id,
                               f"📕 Позиция {thesis.ticker} закрыта — тезис закрыт{sign}.\n"
                               f"Тезис был: {thesis.thesis}")

    for pos in actions.to_draft:
        instrument = deps.universe.get(pos.ticker) or Instrument(
            ticker=pos.ticker, figi=pos.figi, name=pos.name, aliases=frozenset())
        try:
            ctx = await build_council_context(deps, instrument, owner_id,
                                              today=datetime.now(tz=timezone.utc).date())
            draft = await run_thesis_draft(deps.llm, ctx)
        except Exception as exc:
            log.error("thesis_draft_failed", ticker=pos.ticker, error=str(exc))
            continue
        async with deps.session_factory() as session:
            rec = await save_thesis(session, ticker=pos.ticker, figi=pos.figi,
                                    thesis=draft.thesis, invalidation=draft.invalidation,
                                    source="auto", confidence=draft.confidence,
                                    entry_price=pos.avg_price)
            await session.commit()
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="🗑 Удалить тезис", callback_data=f"thesis_del:{rec.id}")]])
        await bot.send_message(
            owner_id,
            f"📌 Обнаружена позиция <b>{pos.ticker}</b> (вес ≥5%) без тезиса.\n"
            f"Сгенерировал тезис: {draft.thesis}\n"
            f"🚨 Инвалидация: {draft.invalidation}\n"
            f"Буду проверять его каждой новостью. Не согласен — удали.",
            reply_markup=kb)
    log.info("positions_synced", closed=len(actions.to_close),
             drafted=len(actions.to_draft))
```

В `scheduler.py` → `build_scheduler` (после score_calls):

```python
from roaring_kittens.positions_sync import sync_positions

    scheduler.add_job(sync_positions, "cron", hour=8, minute=50, args=[deps, bot],
                      id="positions_sync", max_instances=1, coalesce=True)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/positions_sync.py src/roaring_kittens/scheduler.py tests/test_positions_sync.py
git commit -m "feat: daily position sync - close theses with realized return, draft for new positions"
```

---

### Task 10: Thesis Validator в новостном цикле

**Files:**
- Modify: `src/roaring_kittens/scheduler.py` (poll_news)
- Test: дополняется в `tests/test_thesis_gen_check.py` (логика решения — pure)

- [ ] **Step 1: Падающий тест pure-решения (дописать в test_thesis_gen_check.py)**

```python
from roaring_kittens.committee.thesis_check import decide_validation_action


def test_decide_validation_action():
    assert decide_validation_action("invalidated", council_recent=False) == "council"
    assert decide_validation_action("invalidated", council_recent=True) == "notify"
    assert decide_validation_action("weakened", council_recent=False) == "notify"
    assert decide_validation_action("still_valid", council_recent=False) == "nothing"
```

- [ ] **Step 2: Реализовать decide + hook**

В `thesis_check.py` добавить:

```python
def decide_validation_action(status: str, council_recent: bool) -> str:
    """invalidated → авто-комитет (но не чаще 1/сутки на тикер); weakened → уведомить."""
    if status == "invalidated":
        return "notify" if council_recent else "council"
    if status == "weakened":
        return "notify"
    return "nothing"
```

В `scheduler.py` — расширить `poll_news` (после цикла по SOURCES, перед финальным log) и добавить хелпер:

```python
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.committee.render import format_council_verdict
from roaring_kittens.committee.thesis_check import decide_validation_action, run_thesis_check
from roaring_kittens.db.calls import council_ran_recently
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import close_thesis, get_active_theses
from roaring_kittens.news.repository import get_news_for_tickers
from datetime import datetime, timedelta, timezone


async def validate_theses(deps, bot, fresh_tickers: set[str]) -> None:
    """Проверка активных тезисов, чьих тикеров коснулись НОВЫЕ новости."""
    if not fresh_tickers:
        return
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    async with deps.session_factory() as session:
        theses_to_check = [t for t in await get_active_theses(session)
                           if t.ticker in fresh_tickers]
    for thesis in theses_to_check:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [thesis.ticker], since=since)
            recent = await council_ran_recently(session, thesis.ticker, hours=24)
        if not news:
            continue
        try:
            check = await run_thesis_check(deps.llm, thesis, news)
        except Exception as exc:
            log.error("thesis_check_failed", ticker=thesis.ticker, error=str(exc))
            continue
        action = decide_validation_action(check.status, recent)
        if action == "nothing":
            continue
        if action == "notify":
            await bot.send_message(
                owner_id,
                f"⚠️ Тезис по <b>{thesis.ticker}</b> {'СЛОМАН' if check.status == 'invalidated' else 'ослаблен'}: "
                f"{check.reasoning_short}\nТезис: {thesis.thesis}")
            continue
        # action == "council": автозапуск комитета
        await bot.send_message(
            owner_id,
            f"🚨 Новости ломают тезис по <b>{thesis.ticker}</b>: {check.reasoning_short}\n"
            f"Собираю комитет…")
        instrument = deps.universe.resolve(thesis.ticker)
        if instrument is None:
            continue
        try:
            outcome = await run_council_flow(deps, instrument, owner_id)
        except Exception as exc:
            log.error("auto_council_failed", ticker=thesis.ticker, error=str(exc))
            continue
        async with deps.session_factory() as session:
            await close_thesis(session, thesis.id, status="invalidated",
                               realized_return_pct=None,
                               close_reason=f"новости: {check.reasoning_short}")
            await session.commit()
        await bot.send_message(
            owner_id,
            format_council_verdict(instrument.ticker, outcome.state["views"],
                                   outcome.state["debate"], outcome.proposal,
                                   outcome.risk))
```

В `poll_news`: собрать тикеры реально ВСТАВЛЕННЫХ новостей и передать. `save_news` возвращает count, не тикеры — считаем тикеры relevant-новостей источника, где `inserted > 0`:

```python
async def poll_news(deps: Deps, bot=None) -> None:
    alias_map = deps.universe.alias_map()
    total_inserted = 0
    fresh_tickers: set[str] = set()
    for source_id, url in SOURCES:
        items = await fetch_feed(url, source=source_id)
        for item in items:
            item.tickers = match_tickers(f"{item.headline} {item.body or ''}", alias_map)
        relevant = [i for i in items if i.tickers]
        async with deps.session_factory() as session:
            inserted = await save_news(session, relevant)
            await session.commit()
        total_inserted += inserted
        if inserted:
            fresh_tickers |= {t for i in relevant for t in i.tickers}
        log.info("news_polled", source=source_id, fetched=len(items),
                 relevant=len(relevant), inserted=inserted)
    log.info("news_poll_done", inserted=total_inserted)
    if bot is not None and total_inserted:
        try:
            await validate_theses(deps, bot, fresh_tickers)
        except Exception as exc:
            log.error("validate_theses_failed", error=str(exc))
```

Вызовы `poll_news`: в `build_scheduler` job `args=[deps, bot]`; в `main.py` стартовый прогон — `await poll_news(deps, bot)`.

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/scheduler.py src/roaring_kittens/committee/thesis_check.py src/roaring_kittens/main.py tests/test_thesis_gen_check.py
git commit -m "feat: thesis validator on fresh news with auto-council on invalidation"
```

---

### Task 11: Reflective Agent (вс 23:00)

**Files:**
- Create: `src/roaring_kittens/reflection.py`
- Modify: `src/roaring_kittens/scheduler.py`, `src/roaring_kittens/db/calls.py` (ScoredCall.scored_at)
- Test: `tests/test_reflection.py`

- [ ] **Step 1: ScoredCall.scored_at (для недельного среза)**

В `db/calls.py`: dataclass `ScoredCall` — добавить ПОСЛЕДНИМ полем `scored_at: datetime | None = None`; в `get_scored_calls` добавить `call_scores.c.scored_at` в select (последней колонкой) — конструктор `ScoredCall(*r)` подхватит.

- [ ] **Step 2: Падающий тест**

```python
# tests/test_reflection.py
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import roaring_kittens.reflection as refl_mod
from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.reflection import ReflectionOutput, build_reflection_user, run_reflection

NOW = datetime.now(tz=timezone.utc)


def _closed_thesis():
    return ThesisRecord(id=uuid4(), ticker="GAZP", figi="F", opened_at=NOW,
                        closed_at=NOW, status="closed", thesis="рост на контракте",
                        invalidation="i", source="auto", confidence=0.6,
                        entry_price=None, realized_return_pct=Decimal("-3.5"),
                        close_reason="позиция закрыта")


def _scored(verdict="miss"):
    return ScoredCall(ticker="GAZP", stance="bullish", created_at=NOW, source="ask",
                      horizon_days=20, stock_return_pct=Decimal("-2"),
                      imoex_return_pct=Decimal("1.5"), verdict=verdict, scored_at=NOW)


def test_reflection_user_contains_material():
    text = build_reflection_user([_closed_thesis()], [_scored()])
    assert "GAZP" in text and "−3.5" in text.replace("-", "−") or "-3.5" in text
    assert "miss" in text


async def test_run_reflection_skips_when_no_material():
    llm = SimpleNamespace()  # не должен вызываться
    result = await run_reflection(llm, [], [])
    assert result is None


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_run_reflection_returns_output():
    out = ReflectionOutput(weekly_summary="неделя так себе",
                           insights=[refl_mod.InsightDraft(
                               summary="газ не растёт на контрактах",
                               scope="ticker", scope_value="GAZP", confidence=0.6)])
    llm = FakeLLM(out)
    result = await run_reflection(llm, [_closed_thesis()], [_scored()])
    assert result is out
    assert llm.calls == [("weekly_reflection", "gpt-4o")]
```

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/reflection.py
"""Reflective Agent: раз в неделю извлекает уроки из закрытых тезисов и оценённых вызовов."""
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.db.calls import ScoredCall, get_scored_calls
from roaring_kittens.db.insights import save_insight
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import ThesisRecord, get_recently_closed

log = structlog.get_logger()

REFLECTION_MODEL = "gpt-4o"

REFLECTION_SYSTEM = """Ты — рефлексивный агент инвест-бота. Перед тобой итоги недели:
закрытые тезисы (с фактическим результатом) и оценённые прошлые разборы (hit/miss vs IMOEX).
Извлеки 0-3 КОНКРЕТНЫХ переиспользуемых урока (что работает/не работает), только если
для них есть основания в данных. Не выдумывай. Каждому уроку — scope
(ticker|sector|pattern|general) и честная confidence. Плюс короткое резюме недели. По-русски."""


class InsightDraft(BaseModel):
    summary: str = Field(description="переиспользуемый урок одной фразой")
    scope: str = Field(description="ticker|sector|pattern|general")
    scope_value: str | None = None
    confidence: float = Field(ge=0, le=1)


class ReflectionOutput(BaseModel):
    weekly_summary: str = Field(description="2-4 предложения: как прошла неделя")
    insights: list[InsightDraft] = Field(default_factory=list)


def build_reflection_user(closed: list[ThesisRecord],
                          scored: list[ScoredCall]) -> str:
    parts = ["Закрытые тезисы за неделю:"]
    if closed:
        for t in closed:
            ret = "n/a" if t.realized_return_pct is None else f"{t.realized_return_pct}%"
            parts.append(f"- {t.ticker} [{t.status}] «{t.thesis}» → {ret} "
                         f"({t.close_reason})")
    else:
        parts.append("(нет)")
    parts.append("\nОценённые разборы за неделю (20д, vs IMOEX):")
    if scored:
        for s in scored:
            parts.append(f"- {s.ticker} {s.stance} → {s.verdict} "
                         f"(бумага {s.stock_return_pct}%, IMOEX {s.imoex_return_pct}%)")
    else:
        parts.append("(нет)")
    return "\n".join(parts)


async def run_reflection(llm, closed: list[ThesisRecord],
                         scored: list[ScoredCall]) -> ReflectionOutput | None:
    if not closed and not scored:
        return None
    return await llm.parse(
        model=REFLECTION_MODEL, operation="weekly_reflection",
        messages=[{"role": "system", "content": REFLECTION_SYSTEM},
                  {"role": "user", "content": build_reflection_user(closed, scored)}],
        schema=ReflectionOutput)


async def weekly_reflection_job(deps, bot) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    week_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
    async with deps.session_factory() as session:
        closed = await get_recently_closed(session, days=7)
        scored = [s for s in await get_scored_calls(session)
                  if s.scored_at and s.scored_at >= week_ago]
    result = await run_reflection(deps.llm, closed, scored)
    if result is None:
        log.info("reflection_skipped_no_material")
        return
    saved = 0
    for draft in result.insights[:3]:
        embedding = None
        try:
            embedding = await deps.embedder.embed(draft.summary, operation="embed_insight")
        except Exception as exc:
            log.warning("embed_insight_failed", error=str(exc))
        async with deps.session_factory() as session:
            await save_insight(session, summary=draft.summary, scope=draft.scope,
                               scope_value=draft.scope_value,
                               confidence=draft.confidence, embedding=embedding)
            await session.commit()
        saved += 1
    lines = ["📅 <b>Еженедельная рефлексия</b>", "", result.weekly_summary]
    if result.insights:
        lines += ["", "💡 <b>Новые уроки:</b>"]
        lines += [f"• {d.summary} ({round(d.confidence*100)}%)" for d in result.insights[:3]]
    lines += ["", "Уроки будут подмешиваться комитету в похожих ситуациях. /insights — все."]
    await bot.send_message(owner_id, "\n".join(lines))
    log.info("reflection_done", insights=saved)
```

`scheduler.py` → `build_scheduler`:

```python
from roaring_kittens.reflection import weekly_reflection_job

    scheduler.add_job(weekly_reflection_job, "cron", day_of_week="sun",
                      hour=23, minute=0, args=[deps, bot],
                      id="weekly_reflection", max_instances=1, coalesce=True)
```

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/reflection.py src/roaring_kittens/scheduler.py src/roaring_kittens/db/calls.py tests/test_reflection.py
git commit -m "feat: weekly reflective agent generating reusable insights"
```

---

### Task 12: Команды /thesis /insights /history + callbacks

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/thesis.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/telegram/handlers/start.py` (HELP)
- Test: `tests/test_thesis_render.py`

- [ ] **Step 1: Падающий тест рендера**

```python
# tests/test_thesis_render.py
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from roaring_kittens.db.calls import HistoryItem, ScoredCall
from roaring_kittens.db.insights import InsightRecord
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.telegram.handlers.thesis import (
    format_history, format_insights, format_theses,
)

NOW = datetime.now(tz=timezone.utc)


def test_format_theses_lists_active():
    t = ThesisRecord(id=uuid4(), ticker="SBER", figi="F", opened_at=NOW, closed_at=None,
                     status="active", thesis="дивидендная история",
                     invalidation="дивы < 20 ₽", source="auto", confidence=0.6,
                     entry_price=Decimal("280"), realized_return_pct=None,
                     close_reason=None)
    text = format_theses([t])
    assert "SBER" in text and "дивидендная" in text and "дивы < 20" in text


def test_format_theses_empty():
    assert "нет" in format_theses([]).lower()


def test_format_insights():
    i = InsightRecord(id=uuid4(), created_at=NOW, summary="банки под дивы работают",
                      scope="pattern", scope_value="x", confidence=0.8, times_applied=3)
    text = format_insights([i])
    assert "банки под дивы" in text and "80%" in text and "3" in text


def test_format_history_with_scores():
    item = HistoryItem(created_at=NOW, source="council", stance="bullish",
                       confidence=0.7, summary="рост",
                       score_20d=ScoredCall(ticker="SBER", stance="bullish",
                                            created_at=NOW, source="council",
                                            horizon_days=20,
                                            stock_return_pct=Decimal("5"),
                                            imoex_return_pct=Decimal("1"),
                                            verdict="hit"))
    text = format_history("SBER", [item])
    assert "SBER" in text and "hit" in text and "council" in text
```

- [ ] **Step 2: Реализовать handler**

```python
# src/roaring_kittens/telegram/handlers/thesis.py
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from roaring_kittens.db.calls import HistoryItem, get_ticker_history
from roaring_kittens.db.council import get_council_transcript
from roaring_kittens.db.insights import InsightRecord, list_active_insights
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import (
    ThesisRecord, close_thesis, get_active_theses, save_thesis,
)
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import STANCE_EMOJI

log = structlog.get_logger()
router = Router()


def format_theses(theses: list[ThesisRecord]) -> str:
    if not theses:
        return ("📌 Активных тезисов нет.\n"
                "Тезис появляется из /council (кнопка «Принять тезис») или "
                "автоматически для позиций ≥5% портфеля.")
    lines = ["📌 <b>Активные тезисы:</b>", ""]
    for t in theses:
        lines.append(f"<b>{t.ticker}</b> (с {t.opened_at:%d.%m}, {t.source})")
        lines.append(f"🎯 {t.thesis}")
        lines.append(f"🚨 Инвалидация: {t.invalidation}")
        lines.append("")
    lines.append("Каждая свежая новость по тикеру проверяет тезис автоматически.")
    return "\n".join(lines)


def format_insights(items: list[InsightRecord]) -> str:
    if not items:
        return ("💡 Уроков пока нет — они появляются из еженедельной рефлексии "
                "(вс 23:00), когда есть закрытые тезисы или оценённые разборы.")
    lines = ["💡 <b>Уроки бота:</b>", ""]
    for i in items[:15]:
        lines.append(f"• {i.summary}")
        lines.append(f"   [{i.scope}] уверенность {round(i.confidence*100)}% · "
                     f"применён {i.times_applied} раз")
    return "\n".join(lines)


def format_history(ticker: str, items: list[HistoryItem]) -> str:
    if not items:
        return f"🕰 По {ticker} разборов ещё не было."
    lines = [f"🕰 <b>История разборов {ticker}:</b>", ""]
    for h in items:
        score = ""
        if h.score_20d:
            sign = "+" if h.score_20d.excess_pp >= 0 else "−"
            score = (f" → 20д: {sign}{abs(h.score_20d.excess_pp)} пп "
                     f"({h.score_20d.verdict})")
        lines.append(f"{h.created_at:%d.%m} [{h.source}] {STANCE_EMOJI[h.stance]} "
                     f"{h.stance} {round(h.confidence*100)}%{score}")
        lines.append(f"   {h.summary[:150]}")
    return "\n".join(lines)


@router.message(Command("thesis"))
async def cmd_thesis(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer("🔒 Тезисы привязаны к портфелю владельца.")
        return
    async with deps.session_factory() as session:
        theses = await get_active_theses(session)
    await message.answer(format_theses(theses))


@router.message(Command("insights"))
async def cmd_insights(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        items = await list_active_insights(session)
    await message.answer(format_insights(items))


@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer("Формат: <code>/history SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    async with deps.session_factory() as session:
        items = await get_ticker_history(session, instrument.ticker, limit=5)
    await message.answer(format_history(instrument.ticker, items))


@router.callback_query(F.data.startswith("thesis_save:"))
async def cb_thesis_save(callback: CallbackQuery, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with deps.session_factory() as session:
        transcript = await get_council_transcript(session, run_id)
    if not transcript or "meta" not in transcript:
        await callback.message.answer("Не нашёл данные комитета для тезиса.")
        return
    meta, proposal = transcript["meta"], transcript["proposal"]
    from decimal import Decimal
    entry = Decimal(meta["price_at_call"]) if meta.get("price_at_call") else None
    async with deps.session_factory() as session:
        await save_thesis(session, ticker=meta["ticker"], figi=meta["figi"],
                          thesis=proposal["thesis"],
                          invalidation=proposal["invalidation"], source="council",
                          confidence=proposal["confidence"], entry_price=entry)
        await session.commit()
    await callback.message.answer(
        f"📌 Тезис по <b>{meta['ticker']}</b> принят:\n🎯 {proposal['thesis']}\n"
        f"🚨 {proposal['invalidation']}\nБуду проверять его каждой новостью. /thesis — все.")


@router.callback_query(F.data.startswith("thesis_del:"))
async def cb_thesis_del(callback: CallbackQuery, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        thesis_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with deps.session_factory() as session:
        await close_thesis(session, thesis_id, status="closed",
                           realized_return_pct=None, close_reason="удалён владельцем")
        await session.commit()
    await callback.message.answer("🗑 Тезис закрыт.")
```

`handlers/__init__.py`: импорт + `all_routers.include_router(thesis.router)`.
`start.py` HELP_TEXT — в блок владельца добавить:

```python
    "• <code>/thesis</code> — активные тезисы · <code>/insights</code> — уроки бота\n"
    "• <code>/history ТИКЕР</code> — прошлые разборы с исходами\n"
```

- [ ] **Step 3: Push → CI, Commit**

```bash
git add src/roaring_kittens/telegram tests/test_thesis_render.py
git commit -m "feat: /thesis /insights /history commands and thesis callbacks"
```

---

### Task 13: README, деплой, E2E

- [ ] **Step 1: README — раздел после «Комитет»**

```markdown
## Память и тезисы (Phase 3)

У каждой позиции ≥5% портфеля живёт тезис (авто-генерация или из /council кнопкой
«📌 Принять тезис»). Каждая свежая новость по тикеру проверяет тезис (gpt-4o-mini):
invalidated → автозапуск комитета (не чаще 1/сутки на тикер) и закрытие тезиса.
Ежедневный position-sync (08:50) закрывает тезисы проданных позиций с фактическим
результатом. Reflective Agent (вс 23:00) извлекает уроки из закрытых тезисов и
оценённых разборов; уроки и похожие прошлые разборы подмешиваются комитету
(семантический поиск, pgvector + text-embedding-3-small).
Команды: /thesis /insights /history.
```

- [ ] **Step 2: Deploy**

```bash
railway up --service app --ci
```

- [ ] **Step 3: MANUAL — E2E-чеклист (у владельца теперь есть реальные позиции!)**

- [ ] После деплоя в 08:50 (или форсом: временно поменять cron) — position-sync находит новые позиции ≥5% → приходит «📌 Обнаружена позиция … сгенерировал тезис» с кнопкой удаления
- [ ] `/thesis` → список активных тезисов
- [ ] `/council SBER` → в вердикте появилась кнопка «📌 Принять тезис» (если approved buy/hold) → тап → тезис сохранён, старый superseded
- [ ] `/history SBER` → прошлые разборы с исходами (после ночного скоринга)
- [ ] `/insights` → пока пусто с объяснением; после воскресенья — уроки
- [ ] Повторный `/council` по тому же тикеру → в протоколе PM/дебатов виден блок «Память бота» (похожие разборы)
- [ ] В `usage_log` появились операции `embed_call`, `memory_query`, `thesis_draft`, `thesis_check`
- [ ] Продать мелкую позицию (если есть) → назавтра «📕 Позиция закрыта — тезис закрыт, результат …%»

- [ ] **Step 4: Тег**

```bash
git add README.md && git commit -m "docs: phase 3 README" && git tag phase-3
```

---

## Self-review checklist (выполнен при написании)

- **Spec §8 coverage:** episodic (calls+embeddings, semantic similar) ✅ T5 · reflective (insights, weekly agent, times_applied) ✅ T4, T11 · retrieval в промпты с cap ✅ T6 · thesis tracker (создание/валидация/закрытие с исходом) ✅ T3, T8-T10 · импорт позиций → авто-тезис ≥5% ✅ T9 (отклонение №3 задокументировано) · /thesis /insights /history ✅ T12 · weekly reflection в TG ✅ T11
- **Типы согласованы:** `ThesisRecord` (T3) в T8/T9/T10/T11/T12; `SimilarCall`/`HistoryItem` (T5) в T6/T12; `save_call(embedding=...)` (T5) в T7-runner; `ScoredCall.scored_at` добавлен последним с default (T11) — конструкторы в старых тестах не ломаются; `run_council_flow` (T7) в T10; `council_ctx` фикстура расширена `memory_note=None` (T6)
- **Placeholder scan:** полный код в каждом шаге ✅
- **Cost-контроль:** thesis_check — mini и только на СВЕЖИХ новостях; авто-комитет ≤1/сутки/тикер (council_ran_recently); авто-тезис только для ≥5% позиций; embeddings копеечные ✅
- **Приватность:** /thesis и thesis-callbacks owner-gated; /insights и /history публичны (не палят позиции — только разборы) ✅
