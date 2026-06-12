# Roaring Kittens — Phase 0–1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Рабочий Telegram-бот «зеркало портфеля» (Фаза 0) + одиночный AI-аналитик с утренним дайджестом и `/ask` (Фаза 1), задеплоенный на Railway.

**Architecture:** Монолитное async Python-приложение: aiogram 3 (Telegram) → сервисный слой (broker / news / ai / digest) → PostgreSQL 16 + pgvector. APScheduler для cron-задач. Один пользователь (admin) через allow-list; мультитенантность — Фаза 4.

**Tech Stack:** Python 3.12 · aiogram 3 · tinkoff-investments (gRPC SDK) · OpenAI API (structured outputs) · SQLAlchemy 2 async + asyncpg · APScheduler · httpx + feedparser · Docker Compose · Railway.

**Spec:** `docs/superpowers/specs/2026-06-04-roaring-kittens-design.md`

**Сознательные отклонения от спеки (Фаза 1):**
1. **Источники новостей:** спека упоминает «Tinkoff news» и e-disclosure. У публичного Tinkoff Invest gRPC API нет news-эндпоинта, а у e-disclosure нет подтверждённого глобального RSS. Фаза 1 шипится с RBC + Smart-Lab RSS; e-disclosure (пер-компанийные RSS) и другие источники добавляются в Фазе 4 вместе с News Watcher. Архитектура источников — pluggable список, добавление = одна строка конфига.
2. **`news_events.ticker`** (одна колонка в спеке) заменена на `tickers TEXT[]` — одна новость часто касается нескольких бумаг, а `url UNIQUE` не позволяет дублировать строки.
3. **`usage_log`** создаётся уже в Фазе 1 (спека относит к Фазе 2): LLM-вызовы начинаются в Фазе 1, трекинг расходов нужен с первого вызова.
4. **Universe IMOEX:** состав индекса берётся из публичного MOEX ISS API (у Tinkoff SDK нет метода «состав индекса»), маппинг тикер→FIGI — через Tinkoff `instruments.shares()`. Fallback — статический список.

---

## Файловая структура (итог Фазы 0–1)

```
roaring_kittens/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── README.md
├── db/
│   └── schema.sql
├── scripts/
│   ├── smoke_tinkoff.py        # Phase 0 gate: Railway → Tinkoff connectivity
│   └── apply_schema.py         # применяет schema.sql к DATABASE_URL
├── src/roaring_kittens/
│   ├── __init__.py
│   ├── config.py               # Settings (pydantic-settings)
│   ├── logging_setup.py        # structlog JSON
│   ├── main.py                 # entrypoint: bot + scheduler
│   ├── scheduler.py            # APScheduler jobs wiring
│   ├── deps.py                 # Deps-контейнер для handlers/jobs
│   ├── utils/
│   │   ├── __init__.py
│   │   └── retry.py            # retry_async decorator
│   ├── security/
│   │   ├── __init__.py
│   │   └── crypto.py           # Fernet encrypt/decrypt
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py           # async engine + session factory
│   │   └── tables.py           # SQLAlchemy Core: news_events, usage_log
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── models.py           # Position, PortfolioSnapshot, Candle
│   │   ├── tinkoff_client.py   # TinkoffBroker
│   │   └── tech.py             # compute_tech_summary
│   ├── universe/
│   │   ├── __init__.py
│   │   ├── seed.py             # статический fallback-список IMOEX
│   │   └── universe.py         # Universe: ISS + Tinkoff mapping + aliases
│   ├── news/
│   │   ├── __init__.py
│   │   ├── models.py           # NewsItem
│   │   ├── rss.py              # fetch_feed (httpx + feedparser)
│   │   ├── sources.py          # SOURCES config
│   │   ├── matching.py         # match_tickers
│   │   └── repository.py       # save/dedupe/query
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── llm.py              # LLM wrapper + usage logging
│   │   ├── pricing.py          # MODEL_PRICES
│   │   ├── schemas.py          # AnalystReport
│   │   └── analyst.py          # single analyst agent
│   ├── digest/
│   │   ├── __init__.py
│   │   └── morning.py          # builder + job
│   └── telegram/
│       ├── __init__.py
│       ├── middleware.py       # AllowListMiddleware
│       ├── formatting.py       # все text-форматтеры
│       └── handlers/
│           ├── __init__.py     # all_routers
│           ├── start.py
│           ├── portfolio.py
│           ├── ask.py
│           └── digest.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_crypto.py
    ├── test_retry.py
    ├── test_tinkoff_mapping.py
    ├── test_middleware.py
    ├── test_formatting.py
    ├── test_universe.py
    ├── test_rss.py
    ├── test_matching.py
    ├── test_news_repository.py   # integration (TEST_DATABASE_URL)
    ├── test_llm.py
    ├── test_tech.py
    ├── test_analyst.py
    └── test_digest.py
```

Все команды ниже выполняются из корня `D:\Desktop\roaring_kittens`. Тесты: `python -m pytest`.

---

# ФАЗА 0 — Фундамент

### Task 1: Scaffold репозитория

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `README.md`, `src/roaring_kittens/__init__.py`

- [ ] **Step 1: Создать pyproject.toml**

```toml
[project]
name = "roaring-kittens"
version = "0.1.0"
description = "Telegram-native AI investment co-pilot for MOEX"
requires-python = ">=3.12"
dependencies = [
    "aiogram>=3.7",
    "tinkoff-investments>=0.2.0b57",
    "openai>=1.50",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "apscheduler>=3.10,<4",
    "httpx>=0.27",
    "feedparser>=6.0",
    "cryptography>=42",
    "structlog>=24",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "pre-commit>=3.7"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Создать .gitignore**

```
.env
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
build/
dist/
.venv/
```

- [ ] **Step 3: Создать .env.example**

```
TELEGRAM_BOT_TOKEN=123456:replace-me
ADMIN_TELEGRAM_ID=123456789
TINKOFF_TOKEN=t.replace-me-readonly
OPENAI_API_KEY=sk-replace-me
DATABASE_URL=postgresql+asyncpg://kittens:kittens@localhost:5432/kittens
FERNET_KEY=generate-with-Fernet.generate_key
```

- [ ] **Step 4: Создать .pre-commit-config.yaml (secret-scan)**

```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        exclude: ^(\.env\.example|tests/)
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-merge-conflict
      - id: end-of-file-fixer
```

- [ ] **Step 5: Создать README.md (краткий) и пустой пакет**

```markdown
# Roaring Kittens 🐱📈

Telegram-native AI investment co-pilot for MOEX.
Spec: docs/superpowers/specs/2026-06-04-roaring-kittens-design.md
Plan: docs/superpowers/plans/2026-06-12-phase-0-1-foundation-analyst.md

## Dev
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
```

`src/roaring_kittens/__init__.py` — пустой файл.

- [ ] **Step 6: Установить окружение и проверить**

Run: `python -m venv .venv && .venv\Scripts\pip install -e ".[dev]"`
Expected: успешная установка без ошибок резолвинга.

Run: `.venv\Scripts\pre-commit install`
Expected: `pre-commit installed at .git\hooks\pre-commit`

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: scaffold project (pyproject, pre-commit secret-scan, env example)"
```

---

### Task 2: Config (pydantic-settings)

**Files:**
- Create: `src/roaring_kittens/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_config.py
from roaring_kittens.config import Settings


def test_settings_reads_env_and_normalizes_db_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "42")
    monkeypatch.setenv("TINKOFF_TOKEN", "tink")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    # Railway выдаёт postgres:// — мы должны нормализовать в postgresql+asyncpg://
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/db")
    monkeypatch.setenv("FERNET_KEY", "k")
    s = Settings(_env_file=None)
    assert s.admin_telegram_id == 42
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: roaring_kittens.config`)

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/config.py
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    admin_telegram_id: int
    tinkoff_token: str
    openai_api_key: str
    database_url: str
    fernet_key: str
    tz: str = "Europe/Moscow"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/config.py tests/test_config.py
git commit -m "feat: settings with Railway postgres URL normalization"
```

---

### Task 3: Dockerfile + smoke-скрипт + Railway gate (КРИТИЧЕСКИЙ GATE)

Проверяем главный риск: доступен ли Tinkoff Invest API с инфраструктуры Railway (US/EU IP, санкционные фильтры). Если нет — fallback на Timeweb (тот же Dockerfile), решение фиксируется в спеке.

**Files:**
- Create: `Dockerfile`, `scripts/smoke_tinkoff.py`

- [ ] **Step 1: Создать smoke-скрипт**

```python
# scripts/smoke_tinkoff.py
"""Phase 0 gate: проверка связности с Tinkoff Invest API.
Запуск: python scripts/smoke_tinkoff.py (нужен env TINKOFF_TOKEN)."""
import asyncio
import os

from tinkoff.invest import AsyncClient


async def main() -> None:
    token = os.environ["TINKOFF_TOKEN"]
    async with AsyncClient(token) as client:
        accounts = await client.users.get_accounts()
        print(f"SMOKE OK: {len(accounts.accounts)} account(s) visible")
        for acc in accounts.accounts:
            print(f"  - id={acc.id} name={acc.name!r}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Создать Dockerfile (CMD пока — smoke-скрипт; в Task 11 заменим на main)**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY scripts ./scripts
COPY db ./db
CMD ["python", "scripts/smoke_tinkoff.py"]
```

Также создать пустую директорию-заглушку `db/.gitkeep` (schema.sql появится в Task 5; без неё COPY упадёт).

- [ ] **Step 3: Локальная проверка скрипта (с твоей машины, RU-IP)**

Run: `set TINKOFF_TOKEN=<твой read-only токен> && .venv\Scripts\python scripts/smoke_tinkoff.py`
Expected: `SMOKE OK: N account(s) visible`

- [ ] **Step 4: Commit**

```bash
git add Dockerfile scripts/smoke_tinkoff.py db/.gitkeep
git commit -m "feat: tinkoff smoke script + dockerfile for Railway gate"
```

- [ ] **Step 5: MANUAL — Railway setup + gate**

1. `npm i -g @railway/cli` (или scoop/winget), `railway login`
2. `railway init` в корне репо → новый проект `roaring-kittens`
3. В Railway dashboard: добавить сервис из этого репо (Dockerfile detected автоматически)
4. Variables сервиса: `TINKOFF_TOKEN=<read-only токен>`
5. Deploy → открыть Deploy Logs

**GATE — критерий прохождения:** в логах видно `SMOKE OK: N account(s) visible`.

**Если FAIL** (timeout / connection refused / gRPC UNAVAILABLE): Railway не подходит → разворачиваем Timeweb Cloud VPS (Docker, RU-IP), фиксируем решение комментарием в спеке §16, дальше все деплой-шаги выполняются на Timeweb. Код не меняется.

---

### Task 4: Fernet crypto

**Files:**
- Create: `src/roaring_kittens/security/__init__.py`, `src/roaring_kittens/security/crypto.py`
- Test: `tests/test_crypto.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_crypto.py
from cryptography.fernet import Fernet

from roaring_kittens.security.crypto import decrypt_secret, encrypt_secret


def test_roundtrip():
    key = Fernet.generate_key().decode()
    token = "t.super-secret-tinkoff-token"
    blob = encrypt_secret(token, key)
    assert blob != token.encode()
    assert decrypt_secret(blob, key) == token
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/security/crypto.py
from cryptography.fernet import Fernet


def encrypt_secret(plaintext: str, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(plaintext.encode())


def decrypt_secret(blob: bytes, key: str) -> str:
    return Fernet(key.encode()).decrypt(blob).decode()
```

`security/__init__.py` — пустой.

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/security tests/test_crypto.py
git commit -m "feat: fernet secret encryption helpers"
```

---

### Task 5: Retry-декоратор + structlog

**Files:**
- Create: `src/roaring_kittens/utils/__init__.py`, `src/roaring_kittens/utils/retry.py`, `src/roaring_kittens/logging_setup.py`
- Test: `tests/test_retry.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_retry.py
import pytest

from roaring_kittens.utils.retry import retry_async


async def test_retries_then_succeeds():
    calls = {"n": 0}

    @retry_async(attempts=3, base_delay=0.01)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 3


async def test_raises_after_exhaustion():
    @retry_async(attempts=2, base_delay=0.01)
    async def always_fails():
        raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        await always_fails()
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_retry.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/utils/retry.py
import asyncio
import functools

import structlog

log = structlog.get_logger()


def retry_async(attempts: int = 3, base_delay: float = 1.0,
                exceptions: tuple[type[Exception], ...] = (Exception,)):
    """Экспоненциальный backoff: base_delay * 2^attempt."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            for attempt in range(attempts):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    log.warning("retry", fn=fn.__name__, attempt=attempt + 1,
                                delay=delay, error=str(exc))
                    await asyncio.sleep(delay)
        return wrapper
    return decorator
```

```python
# src/roaring_kittens/logging_setup.py
import logging
import sys

import structlog


def configure_logging() -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_retry.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/utils src/roaring_kittens/logging_setup.py tests/test_retry.py
git commit -m "feat: async retry decorator with backoff + structlog json setup"
```

---

### Task 6: Postgres + schema + docker-compose

**Files:**
- Create: `db/schema.sql`, `docker-compose.yml`, `scripts/apply_schema.py`, `src/roaring_kittens/db/__init__.py`, `src/roaring_kittens/db/engine.py`, `src/roaring_kittens/db/tables.py`

- [ ] **Step 1: Создать db/schema.sql (идемпотентная, Phase 0–1 subset)**

```sql
-- db/schema.sql — Roaring Kittens, Phase 0-1
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS news_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    published_at TIMESTAMPTZ NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tickers     TEXT[] NOT NULL DEFAULT '{}',
    source      VARCHAR(50) NOT NULL,
    headline    TEXT NOT NULL,
    body        TEXT,
    url         TEXT UNIQUE NOT NULL,
    embedding   VECTOR(1536)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_events (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_tickers ON news_events USING gin (tickers);

CREATE TABLE IF NOT EXISTS usage_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    operation     VARCHAR(50) NOT NULL,
    model         VARCHAR(50) NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      NUMERIC(10,6) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log (timestamp DESC);
```

(Остальные таблицы спеки — users/theses/episodes/insights/… — добавляются в Фазах 3–4.)

- [ ] **Step 2: Создать docker-compose.yml**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: kittens
      POSTGRES_PASSWORD: kittens
      POSTGRES_DB: kittens
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
  app:
    build: .
    env_file: .env
    depends_on:
      - db
volumes:
  pgdata:
```

- [ ] **Step 3: Создать scripts/apply_schema.py (для Railway-постгреса, где initdb-хук недоступен)**

```python
# scripts/apply_schema.py
"""Применяет db/schema.sql к базе из DATABASE_URL. Идемпотентно."""
import asyncio
import os
from pathlib import Path

import asyncpg


async def main() -> None:
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    sql = Path(__file__).resolve().parents[1].joinpath("db", "schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(sql)  # asyncpg simple-query: multi-statement OK
        print("SCHEMA OK")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Создать engine + tables**

```python
# src/roaring_kittens/db/engine.py
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_size=5, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

```python
# src/roaring_kittens/db/tables.py
from sqlalchemy import TIMESTAMP, Column, Integer, MetaData, Numeric, String, Table, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

metadata = MetaData()

news_events = Table(
    "news_events", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("published_at", TIMESTAMP(timezone=True), nullable=False),
    Column("fetched_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("tickers", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("source", String(50), nullable=False),
    Column("headline", Text, nullable=False),
    Column("body", Text),
    Column("url", Text, nullable=False, unique=True),
)

usage_log = Table(
    "usage_log", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("timestamp", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("operation", String(50), nullable=False),
    Column("model", String(50), nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Numeric(10, 6), nullable=False),
)
```

(Колонка `embedding` не описана в Core-таблице сознательно — в Фазе 1 не используется; SQL-схема её уже содержит.)

- [ ] **Step 5: Проверить локально**

Run: `docker compose up -d db`, подождать 5 сек, затем
`docker compose exec db psql -U kittens -d kittens -c "\dt"`
Expected: таблицы `news_events`, `usage_log` в списке.

- [ ] **Step 6: Commit**

```bash
git add db/schema.sql docker-compose.yml scripts/apply_schema.py src/roaring_kittens/db
git rm --cached db/.gitkeep 2>$null; git add -A
git commit -m "feat: postgres schema (news_events, usage_log) + compose + engine"
```

---

### Task 7: Broker — модели и маппинг портфеля (TDD на чистой функции)

**Files:**
- Create: `src/roaring_kittens/broker/__init__.py`, `src/roaring_kittens/broker/models.py`, `src/roaring_kittens/broker/tinkoff_client.py`
- Test: `tests/test_tinkoff_mapping.py`

- [ ] **Step 1: Падающий тест (маппинг ответа SDK → наши модели; SDK-классы Quotation/MoneyValue настоящие)**

```python
# tests/test_tinkoff_mapping.py
from decimal import Decimal
from types import SimpleNamespace

from tinkoff.invest import MoneyValue, Quotation

from roaring_kittens.broker.tinkoff_client import map_portfolio


def _money(units, nano=0):
    return MoneyValue(currency="rub", units=units, nano=nano)


def test_map_portfolio_filters_shares_and_computes_pnl():
    raw = SimpleNamespace(
        total_amount_portfolio=_money(1_000_000),
        positions=[
            SimpleNamespace(
                figi="BBG004730N88", instrument_type="share",
                quantity=Quotation(units=500, nano=0),
                average_position_price=_money(280),
                current_price=_money(294),
            ),
            SimpleNamespace(  # валюта — должна отфильтроваться
                figi="RUB000UTSTOM", instrument_type="currency",
                quantity=Quotation(units=1000, nano=0),
                average_position_price=_money(1),
                current_price=_money(1),
            ),
        ],
    )
    figi_map = {"BBG004730N88": ("SBER", "Сбер Банк")}
    snap = map_portfolio(raw, figi_map)
    assert snap.total_value == Decimal("1000000")
    assert len(snap.positions) == 1
    p = snap.positions[0]
    assert p.ticker == "SBER" and p.quantity == Decimal("500")
    assert p.pnl_pct == Decimal("5.0")  # (294-280)/280*100
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_tinkoff_mapping.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать models + map_portfolio + TinkoffBroker**

```python
# src/roaring_kittens/broker/models.py
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    ticker: str
    name: str
    figi: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    pnl_pct: Decimal  # (current-avg)/avg * 100, округлено до 0.1


@dataclass(frozen=True)
class PortfolioSnapshot:
    total_value: Decimal
    positions: list[Position]


@dataclass(frozen=True)
class Candle:
    day: date
    open: Decimal
    close: Decimal
    high: Decimal
    low: Decimal
    volume: int
```

```python
# src/roaring_kittens/broker/tinkoff_client.py
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from tinkoff.invest import AsyncClient, CandleInterval
from tinkoff.invest.utils import money_to_decimal, now, quotation_to_decimal

from roaring_kittens.broker.models import Candle, PortfolioSnapshot, Position
from roaring_kittens.utils.retry import retry_async


def map_portfolio(raw, figi_map: dict[str, tuple[str, str]]) -> PortfolioSnapshot:
    """Чистая функция: ответ operations.get_portfolio → PortfolioSnapshot."""
    positions = []
    for p in raw.positions:
        if p.instrument_type != "share":
            continue
        ticker, name = figi_map.get(p.figi, (p.figi, p.figi))
        avg = money_to_decimal(p.average_position_price)
        cur = money_to_decimal(p.current_price)
        pnl = ((cur - avg) / avg * 100).quantize(Decimal("0.1"), ROUND_HALF_UP) if avg else Decimal("0")
        positions.append(Position(
            ticker=ticker, name=name, figi=p.figi,
            quantity=quotation_to_decimal(p.quantity),
            avg_price=avg, current_price=cur, pnl_pct=pnl,
        ))
    return PortfolioSnapshot(
        total_value=money_to_decimal(raw.total_amount_portfolio),
        positions=sorted(positions, key=lambda x: x.ticker),
    )


class TinkoffBroker:
    def __init__(self, token: str):
        self._token = token
        self._figi_map: dict[str, tuple[str, str]] | None = None

    async def _ensure_figi_map(self, client) -> dict[str, tuple[str, str]]:
        if self._figi_map is None:
            resp = await client.instruments.shares()
            self._figi_map = {s.figi: (s.ticker, s.name) for s in resp.instruments}
        return self._figi_map

    @retry_async(attempts=3, base_delay=1.0)
    async def get_portfolio(self) -> PortfolioSnapshot:
        async with AsyncClient(self._token) as client:
            figi_map = await self._ensure_figi_map(client)
            accounts = await client.users.get_accounts()
            raw = await client.operations.get_portfolio(account_id=accounts.accounts[0].id)
            return map_portfolio(raw, figi_map)

    @retry_async(attempts=3, base_delay=1.0)
    async def get_daily_candles(self, figi: str, days: int = 35) -> list[Candle]:
        async with AsyncClient(self._token) as client:
            resp = await client.market_data.get_candles(
                figi=figi, from_=now() - timedelta(days=days), to=now(),
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            )
            return [
                Candle(
                    day=c.time.date(),
                    open=quotation_to_decimal(c.open), close=quotation_to_decimal(c.close),
                    high=quotation_to_decimal(c.high), low=quotation_to_decimal(c.low),
                    volume=c.volume,
                )
                for c in resp.candles if c.is_complete
            ]

    async def list_shares(self) -> dict[str, tuple[str, str]]:
        """ticker -> (figi, name) для маппинга universe."""
        async with AsyncClient(self._token) as client:
            resp = await client.instruments.shares()
            return {s.ticker: (s.figi, s.name) for s in resp.instruments
                    if s.class_code == "TQBR"}
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_tinkoff_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/broker tests/test_tinkoff_mapping.py
git commit -m "feat: tinkoff broker with pure portfolio mapping + daily candles"
```

---

### Task 8: Telegram — allow-list middleware

**Files:**
- Create: `src/roaring_kittens/telegram/__init__.py`, `src/roaring_kittens/telegram/middleware.py`
- Test: `tests/test_middleware.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_middleware.py
from types import SimpleNamespace

from roaring_kittens.telegram.middleware import AllowListMiddleware


async def test_allowed_user_passes():
    mw = AllowListMiddleware(allowed_ids={42})
    called = {"v": False}

    async def handler(event, data):
        called["v"] = True
        return "handled"

    data = {"event_from_user": SimpleNamespace(id=42)}
    result = await mw(handler, event=object(), data=data)
    assert result == "handled" and called["v"]


async def test_unknown_user_is_dropped():
    mw = AllowListMiddleware(allowed_ids={42})

    async def handler(event, data):
        raise AssertionError("must not be called")

    data = {"event_from_user": SimpleNamespace(id=999)}
    assert await mw(handler, event=object(), data=data) is None
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_middleware.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/telegram/middleware.py
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware

log = structlog.get_logger()


class AllowListMiddleware(BaseMiddleware):
    """Фаза 0-1: единственный пользователь — admin. Чужие апдейты молча дропаем."""

    def __init__(self, allowed_ids: set[int]):
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in self.allowed_ids:
            log.info("update_dropped", user_id=getattr(user, "id", None))
            return None
        return await handler(event, data)
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_middleware.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/telegram tests/test_middleware.py
git commit -m "feat: telegram allow-list middleware"
```

---

### Task 9: Telegram — /start, /portfolio + форматтер

**Files:**
- Create: `src/roaring_kittens/telegram/formatting.py`, `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/telegram/handlers/start.py`, `src/roaring_kittens/telegram/handlers/portfolio.py`, `src/roaring_kittens/deps.py`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Падающий тест форматтера**

```python
# tests/test_formatting.py
from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.telegram.formatting import format_portfolio


def _pos(ticker, qty, avg, cur, pnl):
    return Position(ticker=ticker, name=ticker, figi="X", quantity=Decimal(qty),
                    avg_price=Decimal(avg), current_price=Decimal(cur), pnl_pct=Decimal(pnl))


def test_format_portfolio_contains_positions_and_total():
    snap = PortfolioSnapshot(
        total_value=Decimal("1234567.89"),
        positions=[_pos("SBER", "500", "280", "294", "5.0"),
                   _pos("VTBR", "1000", "86.5", "79.2", "-8.4")],
    )
    text = format_portfolio(snap)
    assert "1 234 568" in text          # округление и разделители тысяч
    assert "SBER" in text and "+5.0%" in text
    assert "VTBR" in text and "−8.4%" in text


def test_format_empty_portfolio():
    text = format_portfolio(PortfolioSnapshot(total_value=Decimal("0"), positions=[]))
    assert "пуст" in text.lower()
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать форматтер**

```python
# src/roaring_kittens/telegram/formatting.py
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import PortfolioSnapshot


def _fmt_money(v: Decimal) -> str:
    return f"{v.quantize(Decimal('1'), ROUND_HALF_UP):,}".replace(",", " ")


def _fmt_pct(v: Decimal) -> str:
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v)}%"


def format_portfolio(snap: PortfolioSnapshot) -> str:
    if not snap.positions:
        return "📊 Портфель пуст."
    lines = [f"📊 <b>Портфель</b> — {_fmt_money(snap.total_value)} ₽", ""]
    for p in snap.positions:
        lines.append(
            f"<b>{p.ticker}</b> · {p.quantity} шт · "
            f"{p.avg_price} → {p.current_price} ₽ · {_fmt_pct(p.pnl_pct)}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: PASS

- [ ] **Step 5: Создать Deps и handlers (тонкие, логика в сервисах — юнит-тесты не нужны)**

```python
# src/roaring_kittens/deps.py
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings


@dataclass
class Deps:
    settings: Settings
    broker: TinkoffBroker
    session_factory: async_sessionmaker[AsyncSession]
    # universe/llm добавятся в Фазе 1 (Task 12/15)
```

```python
# src/roaring_kittens/telegram/handlers/start.py
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Портфель"), KeyboardButton(text="📅 Дайджест")],
        [KeyboardButton(text="💡 Спросить"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🐱📈 <b>Roaring Kittens</b>\n\n"
        "Я твой AI-аналитик по Мосбирже.\n"
        "Команды: /portfolio /ask /digest /help",
        reply_markup=MAIN_MENU,
    )
```

```python
# src/roaring_kittens/telegram/handlers/portfolio.py
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import format_portfolio

router = Router()


@router.message(Command("portfolio"))
@router.message(F.text == "📊 Портфель")
async def cmd_portfolio(message: Message, deps: Deps) -> None:
    snap = await deps.broker.get_portfolio()
    await message.answer(format_portfolio(snap))
```

```python
# src/roaring_kittens/telegram/handlers/__init__.py
from aiogram import Router

from roaring_kittens.telegram.handlers import portfolio, start

all_routers = Router()
all_routers.include_router(start.router)
all_routers.include_router(portfolio.router)
```

- [ ] **Step 6: Прогнать все тесты**

Run: `python -m pytest -v`
Expected: все PASS

- [ ] **Step 7: Commit**

```bash
git add src/roaring_kittens/telegram src/roaring_kittens/deps.py tests/test_formatting.py
git commit -m "feat: /start with menu, /portfolio handler + html formatter"
```

---

### Task 10: main.py — entrypoint и локальный запуск

**Files:**
- Create: `src/roaring_kittens/main.py`
- Modify: `Dockerfile` (CMD → main)

- [ ] **Step 1: Реализовать main**

```python
# src/roaring_kittens/main.py
import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings
from roaring_kittens.db.engine import make_engine, make_session_factory
from roaring_kittens.deps import Deps
from roaring_kittens.logging_setup import configure_logging
from roaring_kittens.telegram.handlers import all_routers
from roaring_kittens.telegram.middleware import AllowListMiddleware

log = structlog.get_logger()


async def run() -> None:
    configure_logging()
    settings = Settings()
    engine = make_engine(settings.database_url)
    deps = Deps(
        settings=settings,
        broker=TinkoffBroker(settings.tinkoff_token),
        session_factory=make_session_factory(engine),
    )
    bot = Bot(token=settings.telegram_bot_token,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(deps=deps)
    dp.message.middleware(AllowListMiddleware({settings.admin_telegram_id}))
    dp.include_router(all_routers)
    log.info("bot_starting", admin=settings.admin_telegram_id)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Обновить Dockerfile CMD**

```dockerfile
CMD ["python", "-m", "roaring_kittens.main"]
```

(заменить последнюю строку; остальное без изменений)

- [ ] **Step 3: MANUAL — локальный smoke**

1. Создать бота у @BotFather, получить токен; узнать свой telegram_id (@userinfobot)
2. Заполнить `.env` по `.env.example`
3. Run: `docker compose up -d db && .venv\Scripts\python -m roaring_kittens.main`
4. В Telegram: `/start` → меню; `/portfolio` → реальные позиции из Tinkoff
5. С другого аккаунта (если есть): бот молчит (allow-list работает)

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/main.py Dockerfile
git commit -m "feat: main entrypoint - polling bot with portfolio mirror"
```

---

### Task 11: Деплой Фазы 0 на Railway

- [ ] **Step 1: MANUAL — Railway production setup**

1. В Railway-проект добавить Postgres c pgvector: New Service → Docker Image → `pgvector/pgvector:pg16`, добавить Volume на `/var/lib/postgresql/data`, env `POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB=kittens`
2. В app-сервисе Variables: `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `TINKOFF_TOKEN`, `OPENAI_API_KEY`, `FERNET_KEY`, `DATABASE_URL=postgresql://kittens:<pass>@<internal-host>:5432/kittens` (Railway private networking)
3. `railway up` (или git push, если связан репо)
4. Применить схему: `railway run python scripts/apply_schema.py` → `SCHEMA OK`

- [ ] **Step 2: MANUAL — верификация Фазы 0 (gate)**

- В Telegram: `/portfolio` отвечает реальным портфелем при выключенном локальном процессе (работает именно Railway-инстанс)
- В Railway Logs: JSON-логи `bot_starting`, нет рестарт-лупов за 30 минут

- [ ] **Step 3: Тег**

```bash
git tag phase-0 && git push --tags 2>$null; echo done
```

**=== ФАЗА 0 ЗАВЕРШЕНА: бот-«зеркало портфеля» в проде ===**

---

# ФАЗА 1 — Одиночный AI-аналитик

### Task 12: Universe — IMOEX-40 (MOEX ISS + Tinkoff mapping + aliases)

**Files:**
- Create: `src/roaring_kittens/universe/__init__.py`, `src/roaring_kittens/universe/seed.py`, `src/roaring_kittens/universe/universe.py`
- Modify: `src/roaring_kittens/deps.py` (добавить `universe`)
- Test: `tests/test_universe.py`

- [ ] **Step 1: Создать seed.py (fallback; сверить состав с актуальным IMOEX при имплементации)**

```python
# src/roaring_kittens/universe/seed.py
"""Статический fallback состава IMOEX (~40 бумаг). Обновляется вручную при ребалансировке индекса."""
SEED_TICKERS: list[str] = [
    "SBER", "GAZP", "LKOH", "GMKN", "NVTK", "ROSN", "TATN", "SNGS", "SNGSP",
    "PLZL", "MGNT", "MTSS", "CHMF", "NLMK", "ALRS", "MOEX", "VTBR", "AFKS",
    "RUAL", "YDEX", "OZON", "T", "X5", "PHOR", "IRAO", "HYDR", "AFLT",
    "PIKK", "SMLT", "MAGN", "MTLR", "CBOM", "BSPB", "SELG", "UPRO", "ENPG",
    "TRNFP", "FLOT", "SVCB", "POSI", "ASTR",
]

# Ручные алиасы для матчинга новостей (тикеры, чьи имена в новостях не совпадают
# с официальным названием инструмента). Дополняется по мере эксплуатации.
EXTRA_ALIASES: dict[str, list[str]] = {
    "SBER": ["сбербанк", "сбера", "сбер "],
    "GAZP": ["газпром"],
    "VTBR": ["втб"],
    "LKOH": ["лукойл"],
    "GMKN": ["норникел", "норильский никель"],
    "YDEX": ["яндекс"],
    "OZON": ["озон", "ozon"],
    "T": ["т-банк", "тинькофф", "т-технологии"],
    "X5": ["x5 ", "пятёрочк", "перекрёсток"],
    "MGNT": ["магнит"],
    "AFLT": ["аэрофлот"],
    "ROSN": ["роснефт"],
    "NVTK": ["новатэк"],
    "PLZL": ["полюс"],
    "MOEX": ["мосбирж", "московская биржа"],
}
```

- [ ] **Step 2: Падающий тест**

```python
# tests/test_universe.py
import json

import httpx

from roaring_kittens.universe.universe import Instrument, Universe, parse_iss_tickers

ISS_SAMPLE = {
    "analytics": {
        "columns": ["indexid", "tradedate", "ticker", "shortnames", "weight"],
        "data": [
            ["IMOEX", "2026-06-11", "SBER", "Сбербанк", 14.2],
            ["IMOEX", "2026-06-11", "GAZP", "Газпром", 9.1],
        ],
    }
}


def test_parse_iss_tickers():
    assert parse_iss_tickers(ISS_SAMPLE) == ["SBER", "GAZP"]


async def test_universe_load_maps_figi_and_builds_aliases():
    def iss_handler(request):
        return httpx.Response(200, json=ISS_SAMPLE)

    transport = httpx.MockTransport(iss_handler)

    class FakeBroker:
        async def list_shares(self):
            return {"SBER": ("BBG004730N88", "Сбер Банк"), "GAZP": ("BBG004730RP0", "Газпром"),
                    "AAAA": ("BBGX", "Не из индекса")}

    uni = Universe(broker=FakeBroker(), transport=transport)
    await uni.load()
    assert set(uni.tickers()) == {"SBER", "GAZP"}
    sber = uni.get("SBER")
    assert isinstance(sber, Instrument) and sber.figi == "BBG004730N88"
    assert "сбербанк" in sber.aliases          # из EXTRA_ALIASES
    assert "сбер банк" in sber.aliases          # из имени инструмента
    assert uni.resolve("сбер банк") == sber     # резолв по алиасу
    assert uni.resolve("SBER") == sber          # резолв по тикеру
    assert uni.resolve("nope") is None
```

- [ ] **Step 3: Запустить — FAIL**

Run: `python -m pytest tests/test_universe.py -v`
Expected: FAIL

- [ ] **Step 4: Реализовать**

```python
# src/roaring_kittens/universe/universe.py
from dataclasses import dataclass, field

import httpx
import structlog

from roaring_kittens.universe.seed import EXTRA_ALIASES, SEED_TICKERS

log = structlog.get_logger()

ISS_URL = "https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/IMOEX.json?limit=100"


def parse_iss_tickers(payload: dict) -> list[str]:
    block = payload["analytics"]
    idx = block["columns"].index("ticker")
    return [row[idx] for row in block["data"]]


@dataclass(frozen=True)
class Instrument:
    ticker: str
    figi: str
    name: str
    aliases: frozenset[str] = field(default_factory=frozenset)


class Universe:
    def __init__(self, broker, transport: httpx.BaseTransport | None = None):
        self._broker = broker
        self._transport = transport
        self._by_ticker: dict[str, Instrument] = {}
        self._alias_index: dict[str, str] = {}  # alias -> ticker

    async def load(self) -> None:
        tickers = await self._fetch_index_tickers()
        shares = await self._broker.list_shares()  # ticker -> (figi, name)
        for t in tickers:
            if t not in shares:
                log.warning("universe_ticker_not_in_tinkoff", ticker=t)
                continue
            figi, name = shares[t]
            aliases = {name.lower(), t.lower()} | set(EXTRA_ALIASES.get(t, []))
            self._by_ticker[t] = Instrument(t, figi, name, frozenset(aliases))
            for a in aliases:
                self._alias_index[a] = t
        log.info("universe_loaded", count=len(self._by_ticker))

    async def _fetch_index_tickers(self) -> list[str]:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
                resp = await client.get(ISS_URL)
                resp.raise_for_status()
                return parse_iss_tickers(resp.json())
        except Exception as exc:
            log.warning("iss_unavailable_using_seed", error=str(exc))
            return list(SEED_TICKERS)

    def tickers(self) -> list[str]:
        return list(self._by_ticker)

    def get(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker.upper())

    def resolve(self, query: str) -> Instrument | None:
        q = query.strip().lower()
        direct = self._by_ticker.get(query.strip().upper())
        if direct:
            return direct
        t = self._alias_index.get(q)
        return self._by_ticker.get(t) if t else None

    def alias_map(self) -> dict[str, frozenset[str]]:
        """ticker -> aliases, для news matching."""
        return {t: i.aliases for t, i in self._by_ticker.items()}
```

В `deps.py` добавить поле:

```python
from roaring_kittens.universe.universe import Universe

@dataclass
class Deps:
    settings: Settings
    broker: TinkoffBroker
    session_factory: async_sessionmaker[AsyncSession]
    universe: Universe
```

- [ ] **Step 5: Запустить — PASS (тест universe + все остальные, deps мог сломать import)**

Run: `python -m pytest -v`
Expected: PASS (test_universe и все прежние)

Примечание: `main.py` теперь не компилируется без universe — исправить:

```python
# в main.run(), после создания broker:
from roaring_kittens.universe.universe import Universe
universe = Universe(broker=broker)
await universe.load()
deps = Deps(settings=settings, broker=broker,
            session_factory=make_session_factory(engine), universe=universe)
```

(переменную `broker = TinkoffBroker(settings.tinkoff_token)` вынести до создания Deps)

- [ ] **Step 6: Commit**

```bash
git add src/roaring_kittens/universe src/roaring_kittens/deps.py src/roaring_kittens/main.py tests/test_universe.py
git commit -m "feat: IMOEX universe via MOEX ISS with tinkoff figi mapping and aliases"
```

---

### Task 13: RSS fetcher

**Files:**
- Create: `src/roaring_kittens/news/__init__.py`, `src/roaring_kittens/news/models.py`, `src/roaring_kittens/news/rss.py`, `src/roaring_kittens/news/sources.py`
- Test: `tests/test_rss.py`

- [ ] **Step 1: Падающий тест (fixture-XML, MockTransport)**

```python
# tests/test_rss.py
import httpx

from roaring_kittens.news.rss import fetch_feed

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item>
  <title>Сбербанк отчитался о рекордной прибыли</title>
  <link>https://example.com/news/1</link>
  <description>Прибыль выросла на 20%</description>
  <pubDate>Wed, 11 Jun 2026 09:30:00 +0300</pubDate>
</item>
<item>
  <title>Газпром подписал контракт</title>
  <link>https://example.com/news/2</link>
  <description>Детали контракта</description>
  <pubDate>Wed, 11 Jun 2026 10:00:00 +0300</pubDate>
</item>
</channel></rss>"""


async def test_fetch_feed_parses_entries():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=RSS_XML.encode()))
    entries = await fetch_feed("https://example.com/rss", source="test", transport=transport)
    assert len(entries) == 2
    e = entries[0]
    assert e.headline == "Сбербанк отчитался о рекордной прибыли"
    assert e.url == "https://example.com/news/1"
    assert e.body == "Прибыль выросла на 20%"
    assert e.published_at.year == 2026 and e.source == "test"


async def test_fetch_feed_http_error_returns_empty():
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    assert await fetch_feed("https://example.com/rss", source="test", transport=transport) == []
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_rss.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/news/models.py
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    source: str
    url: str
    headline: str
    body: str | None
    published_at: datetime
    tickers: list[str] = field(default_factory=list)
```

```python
# src/roaring_kittens/news/rss.py
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx
import structlog

from roaring_kittens.news.models import NewsItem

log = structlog.get_logger()


async def fetch_feed(url: str, source: str,
                     transport: httpx.BaseTransport | None = None) -> list[NewsItem]:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=15,
                                     follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        log.warning("rss_fetch_failed", source=source, error=str(exc))
        return []
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        if not getattr(e, "link", None) or not getattr(e, "title", None):
            continue
        if getattr(e, "published_parsed", None):
            published = datetime.fromtimestamp(mktime(e.published_parsed), tz=timezone.utc)
        else:
            published = datetime.now(tz=timezone.utc)
        items.append(NewsItem(
            source=source, url=e.link, headline=e.title,
            body=getattr(e, "summary", None), published_at=published,
        ))
    return items
```

```python
# src/roaring_kittens/news/sources.py
"""Pluggable список RSS-источников. Добавить источник = добавить строку.
e-disclosure: глобального RSS нет, пер-компанийные фиды добавим в Фазе 4."""

SOURCES: list[tuple[str, str]] = [  # (source_id, url)
    ("rbc", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("smartlab", "https://smart-lab.ru/rss/"),
]
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_rss.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/news tests/test_rss.py
git commit -m "feat: rss fetcher with feedparser + sources config (rbc, smart-lab)"
```

---

### Task 14: News → ticker matching

**Files:**
- Create: `src/roaring_kittens/news/matching.py`
- Test: `tests/test_matching.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_matching.py
from roaring_kittens.news.matching import match_tickers

ALIAS_MAP = {
    "SBER": frozenset({"сбер банк", "сбербанк", "sber"}),
    "GAZP": frozenset({"газпром", "gazp"}),
    "T": frozenset({"т-банк", "тинькофф", "t"}),
}


def test_matches_by_alias_case_insensitive():
    assert match_tickers("СБЕРБАНК отчитался о прибыли", ALIAS_MAP) == ["SBER"]


def test_matches_multiple():
    text = "Газпром и Сбербанк договорились о сотрудничестве"
    assert match_tickers(text, ALIAS_MAP) == ["GAZP", "SBER"]


def test_short_alias_requires_word_boundary():
    # 't' не должен матчиться внутри слова "отчитался"
    assert match_tickers("Компания отчиталась", ALIAS_MAP) == []
    assert match_tickers("Т-Банк показал рост", ALIAS_MAP) == ["T"]


def test_no_match():
    assert match_tickers("Погода в Москве", ALIAS_MAP) == []
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_matching.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/news/matching.py
import re


def match_tickers(text: str, alias_map: dict[str, frozenset[str]]) -> list[str]:
    """Алиасы длиной >=4 — substring-матч; короткие — только по границе слова."""
    t = text.lower()
    matched = set()
    for ticker, aliases in alias_map.items():
        for alias in aliases:
            a = alias.strip().lower()
            if not a:
                continue
            if len(a) >= 4:
                if a in t:
                    matched.add(ticker)
                    break
            else:
                if re.search(rf"(?<![a-zа-яё0-9]){re.escape(a)}(?![a-zа-яё0-9])", t):
                    matched.add(ticker)
                    break
    return sorted(matched)
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_matching.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/news/matching.py tests/test_matching.py
git commit -m "feat: news-to-ticker alias matching with word boundaries for short aliases"
```

---

### Task 15: News repository (integration-тест с реальным Postgres)

**Files:**
- Create: `src/roaring_kittens/news/repository.py`, `tests/conftest.py`
- Test: `tests/test_news_repository.py`

- [ ] **Step 1: Создать conftest с DB-фикстурой (skip без TEST_DATABASE_URL)**

```python
# tests/conftest.py
import os
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")  # пример: postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test

requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def db_session_factory():
    import asyncpg
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    raw = TEST_DB.replace("+asyncpg", "")
    schema = Path(__file__).resolve().parents[1].joinpath("db", "schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(raw)
    await conn.execute(schema)
    await conn.execute("TRUNCATE news_events, usage_log")
    await conn.close()

    engine = create_async_engine(TEST_DB)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
```

Подготовка тест-базы (однократно): `docker compose exec db psql -U kittens -c "CREATE DATABASE kittens_test"` и `set TEST_DATABASE_URL=postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test`

- [ ] **Step 2: Падающий тест**

```python
# tests/test_news_repository.py
from datetime import datetime, timedelta, timezone

from tests.conftest import requires_db

from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers, save_news

pytestmark = requires_db


def _item(url, headline="h", tickers=None, age_hours=1):
    return NewsItem(
        source="test", url=url, headline=headline, body="b",
        published_at=datetime.now(tz=timezone.utc) - timedelta(hours=age_hours),
        tickers=tickers or [],
    )


async def test_save_dedupes_by_url(db_session_factory):
    items = [_item("https://x/1", tickers=["SBER"]), _item("https://x/1", tickers=["SBER"])]
    async with db_session_factory() as session:
        inserted = await save_news(session, items)
        await session.commit()
    assert inserted == 1
    async with db_session_factory() as session:
        again = await save_news(session, [_item("https://x/1")])
        await session.commit()
    assert again == 0


async def test_query_by_ticker_and_window(db_session_factory):
    async with db_session_factory() as session:
        await save_news(session, [
            _item("https://x/sber", headline="про сбер", tickers=["SBER"], age_hours=2),
            _item("https://x/gazp", headline="про газпром", tickers=["GAZP"], age_hours=2),
            _item("https://x/old", headline="старое про сбер", tickers=["SBER"], age_hours=100),
        ])
        await session.commit()
    async with db_session_factory() as session:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        rows = await get_news_for_tickers(session, ["SBER"], since=since)
    assert [r.headline for r in rows] == ["про сбер"]
```

- [ ] **Step 3: Запустить — FAIL** (с поднятой тест-базой и TEST_DATABASE_URL)

Run: `python -m pytest tests/test_news_repository.py -v`
Expected: FAIL (ImportError: repository)

- [ ] **Step 4: Реализовать**

```python
# src/roaring_kittens/news/repository.py
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import news_events
from roaring_kittens.news.models import NewsItem


async def save_news(session: AsyncSession, items: list[NewsItem]) -> int:
    """Вставка с дедупом по url. Возвращает число реально вставленных."""
    if not items:
        return 0
    rows = [
        dict(published_at=i.published_at, tickers=i.tickers, source=i.source,
             headline=i.headline, body=i.body, url=i.url)
        for i in items
    ]
    stmt = insert(news_events).values(rows).on_conflict_do_nothing(index_elements=["url"])
    result = await session.execute(stmt)
    return result.rowcount or 0


async def get_news_for_tickers(session: AsyncSession, tickers: list[str],
                               since: datetime, limit: int = 50) -> list[NewsItem]:
    stmt = (
        select(news_events)
        .where(news_events.c.published_at >= since)
        .where(news_events.c.tickers.overlap(tickers))
        .order_by(news_events.c.published_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).fetchall()
    return [
        NewsItem(source=r.source, url=r.url, headline=r.headline, body=r.body,
                 published_at=r.published_at, tickers=list(r.tickers))
        for r in rows
    ]
```

- [ ] **Step 5: Запустить — PASS**

Run: `python -m pytest tests/test_news_repository.py -v`
Expected: PASS (2 passed). Без TEST_DATABASE_URL — SKIPPED (это норм для CI без БД).

- [ ] **Step 6: Commit**

```bash
git add src/roaring_kittens/news/repository.py tests/conftest.py tests/test_news_repository.py
git commit -m "feat: news repository with url dedupe and ticker window queries"
```

---

### Task 16: LLM wrapper + usage logging

**Files:**
- Create: `src/roaring_kittens/ai/__init__.py`, `src/roaring_kittens/ai/pricing.py`, `src/roaring_kittens/ai/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Создать pricing.py**

```python
# src/roaring_kittens/ai/pricing.py
"""USD за 1M токенов (input, output). Сверить с актуальным прайсом OpenAI при имплементации."""
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o4-mini": (1.10, 4.40),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = MODEL_PRICES.get(model, (5.0, 15.0))  # консервативный дефолт для неизвестных моделей
    return input_tokens / 1_000_000 * inp + output_tokens / 1_000_000 * out
```

- [ ] **Step 2: Падающий тест (fake OpenAI client + fake session)**

```python
# tests/test_llm.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel

from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.pricing import estimate_cost


class Echo(BaseModel):
    answer: str


def _fake_response(parsed):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


async def test_parse_returns_schema_and_logs_usage():
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            parse=AsyncMock(return_value=_fake_response(Echo(answer="да")))
        ))
    )
    logged = []

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd):
        logged.append((operation, model, input_tokens, output_tokens, cost_usd))

    llm = LLM(client=fake_client, usage_logger=fake_log)
    result = await llm.parse(model="gpt-4o", operation="test_op",
                             messages=[{"role": "user", "content": "hi"}], schema=Echo)
    assert result.answer == "да"
    assert logged == [("test_op", "gpt-4o", 100, 50, estimate_cost("gpt-4o", 100, 50))]


def test_estimate_cost():
    assert estimate_cost("gpt-4o", 1_000_000, 0) == 2.50
    assert estimate_cost("gpt-4o-mini", 0, 1_000_000) == 0.60
```

- [ ] **Step 3: Запустить — FAIL**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL

- [ ] **Step 4: Реализовать**

```python
# src/roaring_kittens/ai/llm.py
from typing import Any, Awaitable, Callable, TypeVar

import structlog
from pydantic import BaseModel

from roaring_kittens.ai.pricing import estimate_cost
from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)

UsageLogger = Callable[..., Awaitable[None]]  # (operation, model, input_tokens, output_tokens, cost_usd)


class LLM:
    def __init__(self, client: Any, usage_logger: UsageLogger):
        self._client = client
        self._log_usage = usage_logger

    @retry_async(attempts=3, base_delay=2.0)
    async def parse(self, *, model: str, operation: str,
                    messages: list[dict], schema: type[T]) -> T:
        resp = await self._client.chat.completions.parse(
            model=model, messages=messages, response_format=schema,
        )
        u = resp.usage
        cost = estimate_cost(model, u.prompt_tokens, u.completion_tokens)
        await self._log_usage(operation, model, u.prompt_tokens, u.completion_tokens, cost)
        log.info("llm_call", operation=operation, model=model,
                 input=u.prompt_tokens, output=u.completion_tokens, cost=round(cost, 5))
        return resp.choices[0].message.parsed


def make_db_usage_logger(session_factory) -> UsageLogger:
    from roaring_kittens.db.tables import usage_log

    async def _log(operation, model, input_tokens, output_tokens, cost_usd):
        async with session_factory() as session:
            await session.execute(usage_log.insert().values(
                operation=operation, model=model, input_tokens=input_tokens,
                output_tokens=output_tokens, cost_usd=cost_usd,
            ))
            await session.commit()

    return _log
```

- [ ] **Step 5: Запустить — PASS**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/roaring_kittens/ai tests/test_llm.py
git commit -m "feat: llm wrapper with structured outputs, retry and usage cost logging"
```

---

### Task 17: Tech summary из свечей

**Files:**
- Create: `src/roaring_kittens/broker/tech.py`
- Test: `tests/test_tech.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_tech.py
from datetime import date, timedelta
from decimal import Decimal

from roaring_kittens.broker.models import Candle
from roaring_kittens.broker.tech import compute_tech_summary


def _candles(closes: list[int]) -> list[Candle]:
    start = date(2026, 5, 1)
    return [
        Candle(day=start + timedelta(days=i), open=Decimal(c), close=Decimal(c),
               high=Decimal(c + 2), low=Decimal(c - 2), volume=1000)
        for i, c in enumerate(closes)
    ]


def test_summary_changes():
    closes = [100] * 25 + [110, 111, 112, 113, 114, 115]  # 31 свеча, рост в конце
    s = compute_tech_summary(_candles(closes))
    assert s.last_close == Decimal("115")
    assert s.change_1d_pct == Decimal("0.9")    # 115/114
    assert s.change_7d_pct > Decimal("4")        # 115 vs ~110
    assert s.change_30d_pct == Decimal("15.0")   # 115 vs 100
    assert s.high_30d == Decimal("117") and s.low_30d == Decimal("98")


def test_too_few_candles_returns_none():
    assert compute_tech_summary(_candles([100, 101])) is None
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_tech.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/broker/tech.py
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import Candle

MIN_CANDLES = 8


@dataclass(frozen=True)
class TechSummary:
    last_close: Decimal
    change_1d_pct: Decimal
    change_7d_pct: Decimal
    change_30d_pct: Decimal
    high_30d: Decimal
    low_30d: Decimal

    def as_text(self) -> str:
        return (
            f"Последняя цена: {self.last_close} ₽. "
            f"Изменение: 1д {self.change_1d_pct:+}%, 7д {self.change_7d_pct:+}%, "
            f"30д {self.change_30d_pct:+}%. "
            f"Диапазон 30д: {self.low_30d}–{self.high_30d} ₽."
        )


def _pct(cur: Decimal, prev: Decimal) -> Decimal:
    if not prev:
        return Decimal("0")
    return ((cur - prev) / prev * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def compute_tech_summary(candles: list[Candle]) -> TechSummary | None:
    if len(candles) < MIN_CANDLES:
        return None
    candles = sorted(candles, key=lambda c: c.day)
    last30 = candles[-30:]
    closes = [c.close for c in last30]
    last = closes[-1]
    return TechSummary(
        last_close=last,
        change_1d_pct=_pct(last, closes[-2]),
        change_7d_pct=_pct(last, closes[-6] if len(closes) >= 6 else closes[0]),
        change_30d_pct=_pct(last, closes[0]),
        high_30d=max(c.high for c in last30),
        low_30d=min(c.low for c in last30),
    )
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_tech.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/roaring_kittens/broker/tech.py tests/test_tech.py
git commit -m "feat: tech summary (price changes, 30d range) from daily candles"
```

---

### Task 18: Analyst agent

**Files:**
- Create: `src/roaring_kittens/ai/schemas.py`, `src/roaring_kittens/ai/analyst.py`
- Test: `tests/test_analyst.py`

- [ ] **Step 1: Создать схему output**

```python
# src/roaring_kittens/ai/schemas.py
from typing import Literal

from pydantic import BaseModel, Field


class AnalystReport(BaseModel):
    """Structured output одиночного аналитика (Фаза 1)."""
    ticker: str
    stance: Literal["bullish", "bearish", "neutral"]
    summary: str = Field(description="2-4 предложения: главный вывод по бумаге сейчас")
    key_points: list[str] = Field(description="3-6 ключевых фактов из данных")
    risks: list[str] = Field(description="1-4 главных риска")
    confidence: float = Field(ge=0, le=1, description="насколько данных достаточно для вывода")
```

- [ ] **Step 2: Падающий тест (мокаем LLM, проверяем сборку промпта и проброс)**

```python
# tests/test_analyst.py
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from roaring_kittens.ai.analyst import build_analyst_messages, run_analyst
from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.tech import TechSummary
from roaring_kittens.news.models import NewsItem

TECH = TechSummary(last_close=Decimal("295"), change_1d_pct=Decimal("0.5"),
                   change_7d_pct=Decimal("2.1"), change_30d_pct=Decimal("5.4"),
                   high_30d=Decimal("298"), low_30d=Decimal("279"))
NEWS = [NewsItem(source="rbc", url="https://x/1", headline="Сбер показал рекордную прибыль",
                 body="детали", published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])]


def test_messages_contain_data_and_guardrails():
    msgs = build_analyst_messages("SBER", TECH, NEWS, question="докупать?")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "не выдумывай числа" in system.lower()
    assert "295" in user and "Сбер показал рекордную прибыль" in user
    assert "докупать?" in user


async def test_run_analyst_calls_llm_with_schema():
    fake_llm = AsyncMock()
    fake_llm.parse.return_value = AnalystReport(
        ticker="SBER", stance="bullish", summary="s", key_points=["k"], risks=["r"], confidence=0.8)
    report = await run_analyst(fake_llm, "SBER", TECH, NEWS, question=None)
    assert report.stance == "bullish"
    kwargs = fake_llm.parse.call_args.kwargs
    assert kwargs["schema"] is AnalystReport
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["operation"] == "analyst"
```

- [ ] **Step 3: Запустить — FAIL**

Run: `python -m pytest tests/test_analyst.py -v`
Expected: FAIL

- [ ] **Step 4: Реализовать**

```python
# src/roaring_kittens/ai/analyst.py
from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.tech import TechSummary
from roaring_kittens.news.models import NewsItem

ANALYST_MODEL = "gpt-4o"

SYSTEM_PROMPT = """Ты — аналитик российского фондового рынка (Московская биржа).
Твоя задача — дать честный, взвешенный разбор бумаги на основе ТОЛЬКО предоставленных данных.

Правила:
- НЕ выдумывай числа. Все цены и проценты бери из блока «Техника». Если данных нет — так и скажи.
- Новости оценивай критично: пресс-релизы и пересказы — слабый сигнал.
- Это не инвестиционная рекомендация, а аналитический разбор для частного инвестора.
- Пиши по-русски, кратко и по делу."""


def _format_news(news: list[NewsItem]) -> str:
    if not news:
        return "Свежих новостей по бумаге нет."
    lines = []
    for n in news[:15]:
        lines.append(f"- [{n.published_at:%d.%m %H:%M}] {n.headline} ({n.source})")
    return "\n".join(lines)


def build_analyst_messages(ticker: str, tech: TechSummary | None,
                           news: list[NewsItem], question: str | None) -> list[dict]:
    tech_text = tech.as_text() if tech else "Технических данных недостаточно."
    user = (
        f"Тикер: {ticker}\n\n"
        f"Техника:\n{tech_text}\n\n"
        f"Новости (последние):\n{_format_news(news)}\n"
    )
    if question:
        user += f"\nВопрос пользователя: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def run_analyst(llm: LLM, ticker: str, tech: TechSummary | None,
                      news: list[NewsItem], question: str | None) -> AnalystReport:
    messages = build_analyst_messages(ticker, tech, news, question)
    return await llm.parse(model=ANALYST_MODEL, operation="analyst",
                           messages=messages, schema=AnalystReport)
```

- [ ] **Step 5: Запустить — PASS**

Run: `python -m pytest tests/test_analyst.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/roaring_kittens/ai/schemas.py src/roaring_kittens/ai/analyst.py tests/test_analyst.py
git commit -m "feat: single analyst agent with anti-hallucination guardrails"
```

---

### Task 19: /ask handler + форматтер отчёта

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/ask.py`
- Modify: `src/roaring_kittens/telegram/formatting.py`, `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/deps.py` (поле `llm`), `src/roaring_kittens/main.py`
- Test: `tests/test_formatting.py` (дополнить)

- [ ] **Step 1: Падающий тест форматтера отчёта (добавить в tests/test_formatting.py)**

```python
# добавить в tests/test_formatting.py
from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.telegram.formatting import format_analyst_report


def test_format_analyst_report():
    r = AnalystReport(ticker="SBER", stance="bullish",
                      summary="Выглядит сильно.", key_points=["Прибыль растёт"],
                      risks=["Перекупленность"], confidence=0.8)
    text = format_analyst_report(r)
    assert "SBER" in text and "🟢" in text          # bullish → зелёный
    assert "Прибыль растёт" in text and "Перекупленность" in text
    assert "80%" in text                              # confidence
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: FAIL (новый тест)

- [ ] **Step 3: Реализовать форматтер (добавить в formatting.py)**

```python
# добавить в src/roaring_kittens/telegram/formatting.py
from roaring_kittens.ai.schemas import AnalystReport

STANCE_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪️"}


def format_analyst_report(r: AnalystReport) -> str:
    lines = [
        f"{STANCE_EMOJI[r.stance]} <b>{r.ticker}</b> — {r.stance} "
        f"(уверенность {round(r.confidence * 100)}%)",
        "",
        r.summary,
        "",
        "<b>Ключевое:</b>",
        *[f"• {p}" for p in r.key_points],
        "",
        "<b>Риски:</b>",
        *[f"⚠️ {p}" for p in r.risks],
        "",
        "<i>Это аналитический разбор, не инвестрекомендация.</i>",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: PASS

- [ ] **Step 5: Handler + wiring**

```python
# src/roaring_kittens/telegram/handlers/ask.py
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.deps import Deps
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.telegram.formatting import format_analyst_report

router = Router()

USAGE = "Формат: <code>/ask SBER</code> или <code>/ask SBER стоит докупать?</code>"


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer(USAGE)
        return
    parts = command.args.split(maxsplit=1)
    instrument = deps.universe.resolve(parts[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{parts[0]}». {USAGE}")
        return
    question = parts[1] if len(parts) > 1 else None

    progress = await message.answer(f"🤖 Анализирую {instrument.ticker}…")
    candles = await deps.broker.get_daily_candles(instrument.figi)
    tech = compute_tech_summary(candles)
    since = datetime.now(tz=timezone.utc) - timedelta(days=3)
    async with deps.session_factory() as session:
        news = await get_news_for_tickers(session, [instrument.ticker], since=since)
    report = await run_analyst(deps.llm, instrument.ticker, tech, news, question)
    await progress.edit_text(format_analyst_report(report))
```

В `deps.py` добавить поле `llm: LLM`:

```python
from roaring_kittens.ai.llm import LLM
# в @dataclass Deps:
    llm: LLM
```

В `handlers/__init__.py` добавить:

```python
from roaring_kittens.telegram.handlers import ask
all_routers.include_router(ask.router)
```

В `main.run()` создать LLM и передать в Deps:

```python
from openai import AsyncOpenAI
from roaring_kittens.ai.llm import LLM, make_db_usage_logger

session_factory = make_session_factory(engine)
llm = LLM(client=AsyncOpenAI(api_key=settings.openai_api_key),
          usage_logger=make_db_usage_logger(session_factory))
deps = Deps(settings=settings, broker=broker, session_factory=session_factory,
            universe=universe, llm=llm)
```

- [ ] **Step 6: Прогнать все тесты + MANUAL smoke**

Run: `python -m pytest -v`
Expected: все PASS

MANUAL: запустить бота локально, `/ask SBER` → через ~10 сек приходит разбор с реальной техникой (новостей может не быть — БД пуста до Task 20, это ок: «Свежих новостей нет»).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: /ask command - single analyst run with tech + news context"
```

---

### Task 20: News polling job + scheduler

**Files:**
- Create: `src/roaring_kittens/scheduler.py`
- Modify: `src/roaring_kittens/main.py`

- [ ] **Step 1: Реализовать scheduler с news poll**

```python
# src/roaring_kittens/scheduler.py
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from roaring_kittens.deps import Deps
from roaring_kittens.news.matching import match_tickers
from roaring_kittens.news.repository import save_news
from roaring_kittens.news.rss import fetch_feed
from roaring_kittens.news.sources import SOURCES

log = structlog.get_logger()


async def poll_news(deps: Deps) -> None:
    alias_map = deps.universe.alias_map()
    total_inserted = 0
    for source_id, url in SOURCES:
        items = await fetch_feed(url, source=source_id)
        for item in items:
            item.tickers = match_tickers(f"{item.headline} {item.body or ''}", alias_map)
        relevant = [i for i in items if i.tickers]
        async with deps.session_factory() as session:
            inserted = await save_news(session, relevant)
            await session.commit()
        total_inserted += inserted
        log.info("news_polled", source=source_id, fetched=len(items),
                 relevant=len(relevant), inserted=inserted)
    log.info("news_poll_done", inserted=total_inserted)


def build_scheduler(deps: Deps, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=deps.settings.tz)
    scheduler.add_job(poll_news, "interval", minutes=30, args=[deps],
                      id="poll_news", max_instances=1, coalesce=True)
    # morning digest добавится в Task 21
    return scheduler
```

- [ ] **Step 2: Подключить в main.run() (перед start_polling)**

```python
from roaring_kittens.scheduler import build_scheduler, poll_news

scheduler = build_scheduler(deps, bot)
scheduler.start()
await poll_news(deps)  # первый прогон сразу при старте, чтобы БД не была пустой
```

- [ ] **Step 3: MANUAL — проверить**

Запустить бота локально, в логах: `news_polled` по rbc и smartlab с ненулевым `fetched`; `/ask SBER` теперь может включать свежие новости (если что-то релевантное публиковалось).

Если smart-lab RSS отдаёт ошибку/пустоту — лог `rss_fetch_failed`, бот живёт дальше (graceful degradation работает). URL источника поправить по факту.

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/scheduler.py src/roaring_kittens/main.py
git commit -m "feat: news polling job every 30min with startup run"
```

---

### Task 21: Утренний дайджест + /digest

**Files:**
- Create: `src/roaring_kittens/digest/__init__.py`, `src/roaring_kittens/digest/morning.py`, `src/roaring_kittens/telegram/handlers/digest.py`
- Modify: `src/roaring_kittens/scheduler.py`, `src/roaring_kittens/telegram/handlers/__init__.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Падающий тест билдера**

```python
# tests/test_digest.py
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.digest.morning import build_digest_text, run_morning_digest
from roaring_kittens.news.models import NewsItem

SNAP = PortfolioSnapshot(
    total_value=Decimal("1000000"),
    positions=[Position(ticker="SBER", name="Сбер", figi="F", quantity=Decimal("500"),
                        avg_price=Decimal("280"), current_price=Decimal("294"),
                        pnl_pct=Decimal("5.0"))],
)
NEWS = {"SBER": [NewsItem(source="rbc", url="https://x/1", headline="Сбер: рекордная прибыль",
                          body=None, published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])]}


def test_build_digest_contains_portfolio_news_and_ai():
    text = build_digest_text(SNAP, NEWS, ai_summary="Рынок спокоен, следи за ЦБ.")
    assert "Портфель" in text and "SBER" in text
    assert "Сбер: рекордная прибыль" in text
    assert "Рынок спокоен" in text


def test_build_digest_without_news():
    text = build_digest_text(SNAP, {}, ai_summary=None)
    assert "нет свежих новостей" in text.lower()
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_digest.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/digest/morning.py
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.deps import Deps
from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.telegram.formatting import format_portfolio

log = structlog.get_logger()

DIGEST_MODEL = "gpt-4o"


class DigestSummary(BaseModel):
    market_comment: str = Field(description="2-3 предложения: что важного для портфеля из новостей")
    watch_today: list[str] = Field(description="0-3 пункта: за чем следить сегодня")


DIGEST_SYSTEM = """Ты — утренний аналитик-ассистент частного инвестора на Мосбирже.
По его портфелю и ночным новостям дай короткий комментарий: что важно, за чем следить.
Не выдумывай числа и события. Если новостей мало — так и скажи. Пиши по-русски."""


def build_digest_text(snap: PortfolioSnapshot, news_by_ticker: dict[str, list[NewsItem]],
                      ai_summary: str | None) -> str:
    parts = ["☀️ <b>Доброе утро!</b>", "", format_portfolio(snap), ""]
    if news_by_ticker:
        parts.append("📰 <b>Новости по позициям:</b>")
        for ticker, items in news_by_ticker.items():
            for n in items[:3]:
                parts.append(f"• <b>{ticker}</b>: {n.headline}")
        parts.append("")
    else:
        parts.append("📰 По твоим позициям нет свежих новостей.\n")
    if ai_summary:
        parts.append(f"🤖 {ai_summary}")
    return "\n".join(parts)


async def run_morning_digest(deps: Deps, bot, chat_id: int) -> None:
    snap = await deps.broker.get_portfolio()
    tickers = [p.ticker for p in snap.positions]
    since = datetime.now(tz=timezone.utc) - timedelta(hours=16)
    news_by_ticker: dict[str, list[NewsItem]] = {}
    if tickers:
        async with deps.session_factory() as session:
            all_news = await get_news_for_tickers(session, tickers, since=since)
        for n in all_news:
            for t in n.tickers:
                if t in tickers:
                    news_by_ticker.setdefault(t, []).append(n)

    ai_summary = None
    if news_by_ticker:
        headlines = "\n".join(f"- {t}: {n.headline}" for t, items in news_by_ticker.items()
                              for n in items[:3])
        positions = ", ".join(f"{p.ticker} ({p.pnl_pct:+}%)" for p in snap.positions)
        try:
            result = await deps.llm.parse(
                model=DIGEST_MODEL, operation="morning_digest",
                messages=[{"role": "system", "content": DIGEST_SYSTEM},
                          {"role": "user", "content": f"Портфель: {positions}\n\nНовости:\n{headlines}"}],
                schema=DigestSummary,
            )
            watch = "".join(f"\n• {w}" for w in result.watch_today)
            ai_summary = result.market_comment + (f"\n\n👀 <b>Следить:</b>{watch}" if watch else "")
        except Exception as exc:
            log.error("digest_llm_failed", error=str(exc))

    await bot.send_message(chat_id, build_digest_text(snap, news_by_ticker, ai_summary))
    log.info("digest_sent", tickers=len(tickers), with_ai=ai_summary is not None)
```

```python
# src/roaring_kittens/telegram/handlers/digest.py
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest

router = Router()


@router.message(Command("digest"))
@router.message(F.text == "📅 Дайджест")
async def cmd_digest(message: Message, deps: Deps) -> None:
    await message.answer("⏳ Собираю дайджест…")
    await run_morning_digest(deps, message.bot, message.chat.id)
```

В `handlers/__init__.py`:

```python
from roaring_kittens.telegram.handlers import digest
all_routers.include_router(digest.router)
```

В `scheduler.py` → `build_scheduler` добавить cron:

```python
from roaring_kittens.digest.morning import run_morning_digest

    scheduler.add_job(run_morning_digest, "cron", hour=9, minute=0,
                      args=[deps, bot, deps.settings.admin_telegram_id],
                      id="morning_digest", max_instances=1, coalesce=True)
```

- [ ] **Step 4: Запустить тесты — PASS**

Run: `python -m pytest -v`
Expected: все PASS

- [ ] **Step 5: MANUAL — `/digest` в Telegram**

Локальный запуск → `/digest` → приходит дайджест: портфель + новости (если успели накопиться) + AI-комментарий.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: morning digest (cron 9:00 MSK) + /digest command"
```

---

### Task 22: Финал Фазы 1 — деплой, README, верификация

- [ ] **Step 1: Обновить README**

```markdown
# Roaring Kittens 🐱📈

Telegram-native AI investment co-pilot for MOEX (личный pet-проект).

**Сейчас (Phase 1):** зеркало портфеля Tinkoff, новостной пайплайн (RBC, Smart-Lab),
одиночный AI-аналитик (`/ask SBER`), утренний дайджест в 9:00 МСК.

**Дальше (Phases 2-4):** мультиагентный комитет (Bull/Bear-дебаты), память и тезисы,
HIGH-impact алерты, мультитенантность. См. docs/superpowers/specs/.

## Команды бота
/portfolio — портфель и P&L · /ask TICKER [вопрос] — AI-разбор бумаги ·
/digest — дайджест сейчас · /start — меню

## Dev
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
docker compose up -d db
python -m pytest                      # юнит-тесты
set TEST_DATABASE_URL=postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test
python -m pytest                      # + integration

## Deploy (Railway)
railway up
railway run python scripts/apply_schema.py
```

- [ ] **Step 2: Деплой на Railway**

Run: `railway up`
Затем убедиться, что переменная `OPENAI_API_KEY` задана в сервисе.

- [ ] **Step 3: MANUAL — E2E-чеклист Фазы 1 (на проде)**

- [ ] `/portfolio` → реальные позиции
- [ ] `/ask SBER` → разбор с техникой за 30 дней; цены в ответе совпадают с реальными (анти-галлюцинация: числа приходят из кода)
- [ ] `/ask сбер стоит докупать?` → резолв по алиасу работает, вопрос учтён в ответе
- [ ] `/ask XXXX` → вежливая ошибка «не знаю бумагу»
- [ ] `/digest` → дайджест с новостями и AI-комментарием
- [ ] В логах Railway: `news_polled` каждые 30 минут, `llm_call` с cost
- [ ] В БД: `SELECT count(*) FROM news_events` растёт; `SELECT sum(cost_usd) FROM usage_log` — адекватные суммы (<$0.10 за разбор)
- [ ] Дождаться следующего утра: дайджест пришёл в 9:00 МСК сам

- [ ] **Step 4: Тег и финальный коммит**

```bash
git add -A && git commit -m "docs: phase 1 README" && git tag phase-1
```

**=== ФАЗА 1 ЗАВЕРШЕНА: одиночный AI-аналитик в проде. Дальше — план Фазы 2 (мультиагентный комитет) отдельным документом ===**

---

## Self-review checklist (выполнен при написании)

- **Spec coverage Фазы 0:** repo/Docker/Postgres+pgvector ✅ (T1, T6) · smoke Railway→Tinkoff gate ✅ (T3) · Fernet ✅ (T4) · aiogram skeleton + allow-list ✅ (T8-9) · Tinkoff connect + /portfolio ✅ (T7, T9-10) · логи + error-каркас ✅ (T5)
- **Spec coverage Фазы 1:** парсеры RSS ✅ (T13, отклонение №1 задокументировано) · один агент structured output ✅ (T16, T18) · /ask ✅ (T19) · утренний дайджест ✅ (T21) · universe IMOEX-40 ✅ (T12)
- **Анти-галлюцинации из §11 спеки:** цены только из Tinkoff (tech.py), guardrail в system prompt, Pydantic-валидация — ✅
- **Типы консистентны:** `Deps` расширяется в T12 (universe) и T19 (llm) с правкой main.py на каждом шаге; `NewsItem` единый для rss/matching/repository/digest; `TechSummary.as_text()` используется в analyst — ✅
- **Placeholder scan:** все шаги содержат конкретный код/команды; manual-шаги — чеклисты с критериями ✅
