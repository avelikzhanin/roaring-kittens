# Phase 2 «Мультиагентный комитет» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Команда `/council TICKER`: 4 специалиста (News/Technical/Fundamentals/Sentiment) параллельно → adversarial Bull/Bear дебаты (≤3 раунда, early-exit при сходимости) → Portfolio Manager (вердикт+тезис) → Risk Manager с правом вето; каждый вердикт пишется в `calls` (track-record с первого дня), полный протокол — по кнопке.

**Architecture:** LangGraph StateGraph поверх существующего `LLM`-враппера (без langchain-openai): узлы — обычные async-функции, состояние — TypedDict. Данные собираются один раз в `CouncilContext` (свечи 90д + индикаторы, новости 7д, дивиденды из Tinkoff, позиция владельца). Cost-routing: специалисты/PM — gpt-4o, дебаты/Risk — o4-mini. Транскрипты — в `council_runs` (JSONB).

**Tech Stack:** существующий + `langgraph>=0.2` (единственная новая зависимость).

**Spec:** `docs/superpowers/specs/2026-06-04-roaring-kittens-design.md` §7.

**Verification model:** локального Python нет — тесты в GitHub Actions CI (push → `gh run watch`), задачи батчами. Деплой: `railway up --service app --ci`.

**Сознательные отклонения от спеки:**
1. **`/ask` остаётся одиночным аналитиком**, комитет — отдельная команда `/council` (спека: /ask = комитет). Причина: полный прогон стоит ~$0.20–0.40 и идёт 60–120 сек — губить дешёвый быстрый /ask нельзя; гости сохраняют /ask, комитет в v1 — только владельцу.
2. **Fundamentals-данные = дивиденды из Tinkoff `get_dividends`** (история 3 года + объявленные, доходность считается кодом). МСФО/e-disclosure — Фаза 4; `get_asset_fundamentals` не трогаем (другой контур API, отдельная проверка).
3. **Risk hard-limits упрощены**: концентрация >15% (при непустом портфеле) и переуверенность-на-тонких-данных. Секторных лимитов нет — нет данных о секторах.
4. **Без сайзинга**: счёт владельца ПУСТОЙ — PM работает в «режиме идей» (buy = «идея на покупку»), Risk не делит на нулевой портфель.
5. **LangGraph без Postgres-checkpointer** (in-memory): упавший прогон = повторный запуск за ~$0.3, инфраструктура резюма не окупается.

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── committee/
│   ├── __init__.py
│   ├── schemas.py          # NEW: SpecialistView, DebateTurn, Proposal, RiskReview
│   ├── context.py          # NEW: CouncilContext + build_council_context
│   ├── specialists.py      # NEW: 4 промпта + parallel runner
│   ├── debate.py           # NEW: bull/bear ход + is_converged
│   ├── manager.py          # NEW: Portfolio Manager
│   ├── risk.py             # NEW: hard_checks + Risk agent
│   ├── graph.py            # NEW: LangGraph wiring
│   └── render.py           # NEW: verdict + protocol (chunked)
├── broker/
│   ├── models.py           # MOD: + DividendItem
│   ├── tinkoff_client.py   # MOD: + get_dividends
│   ├── tech.py             # MOD: + Indicators (RSI14/MA20/MA50/volume)
│   ├── fundamentals.py     # NEW: format_dividend_summary (pure)
│   └── position_note.py    # NEW: pure fns из ask.py + вес позиции
├── db/
│   ├── tables.py           # MOD: + council_runs
│   └── council.py          # NEW: save/get транскриптов
└── telegram/handlers/
    ├── ask.py              # MOD: build_position_note → импорт pure fn
    ├── council.py          # NEW: /council + кнопка протокола
    ├── start.py            # MOD: HELP_TEXT
    └── __init__.py         # MOD: + council
db/schema.sql               # MOD: + council_runs
pyproject.toml              # MOD: + langgraph
tests/
├── test_tech_indicators.py # NEW
├── test_fundamentals.py    # NEW
├── test_position_note.py   # NEW
├── test_council_context.py # NEW
├── test_specialists.py     # NEW
├── test_debate.py          # NEW
├── test_manager_risk.py    # NEW
├── test_council_graph.py   # NEW (e2e на FakeLLM)
├── test_council_repo.py    # NEW (integration)
├── test_council_render.py  # NEW
└── conftest.py             # MOD: truncate council_runs
```

---

### Task 1: Зависимость langgraph

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Добавить в dependencies (после structlog)**

```toml
    "langgraph>=0.2",
```

- [ ] **Step 2: Commit (CI на следующем пуше проверит install)**

```bash
git add pyproject.toml
git commit -m "feat: add langgraph dependency for committee orchestration"
```

---

### Task 2: Индикаторы (RSI/MA/объёмы) — код, не LLM

**Files:**
- Modify: `src/roaring_kittens/broker/tech.py`
- Test: `tests/test_tech_indicators.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_tech_indicators.py
from datetime import date, timedelta
from decimal import Decimal

from roaring_kittens.broker.models import Candle
from roaring_kittens.broker.tech import Indicators, compute_indicators


def _candles(closes, volumes=None):
    start = date(2026, 3, 1)
    volumes = volumes or [1000] * len(closes)
    return [Candle(day=start + timedelta(days=i), open=Decimal(c), close=Decimal(c),
                   high=Decimal(c + 1), low=Decimal(c - 1), volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))]


def test_rsi_extremes():
    rising = _candles(list(range(100, 160)))     # только рост -> RSI 100
    falling = _candles(list(range(160, 100, -1)))
    assert compute_indicators(rising).rsi14 == Decimal("100.0")
    assert compute_indicators(falling).rsi14 == Decimal("0.0")


def test_moving_averages_and_volume_ratio():
    closes = [100] * 55 + [110] * 5  # 60 свечей
    volumes = [1000] * 55 + [3000] * 5
    ind = compute_indicators(_candles(closes, volumes))
    assert ind.ma20 == Decimal("102.5")          # (15*100 + 5*110)/20
    assert ind.ma50 == Decimal("101.0")          # (45*100 + 5*110)/50
    # long_avg по 30 последним = (25*1000 + 5*3000)/30 = 1333.33; 3000/1333.33 = 2.25 -> 2.3
    assert ind.volume_ratio == Decimal("2.3")


def test_insufficient_data_gives_nones():
    ind = compute_indicators(_candles([100, 101, 102]))
    assert ind.rsi14 is None and ind.ma20 is None and ind.ma50 is None
    assert ind.volume_ratio is None


def test_as_text_mentions_available_only():
    ind = Indicators(rsi14=Decimal("43.2"), ma20=Decimal("301.2"), ma50=None,
                     volume_ratio=Decimal("1.3"))
    text = ind.as_text(last_close=Decimal("295"))
    assert "RSI(14): 43.2" in text and "MA20" in text and "MA50" not in text
```

- [ ] **Step 2: Реализовать (дописать в tech.py)**

```python
# добавить в src/roaring_kittens/broker/tech.py
RSI_PERIOD = 14
VOL_SHORT, VOL_LONG = 5, 30


@dataclass(frozen=True)
class Indicators:
    rsi14: Decimal | None
    ma20: Decimal | None
    ma50: Decimal | None
    volume_ratio: Decimal | None  # средний объём 5д / средний объём 30д

    def as_text(self, last_close: Decimal | None = None) -> str:
        parts = []
        if self.rsi14 is not None:
            parts.append(f"RSI(14): {self.rsi14}")
        if self.ma20 is not None:
            rel = ""
            if last_close is not None:
                rel = " (цена выше)" if last_close > self.ma20 else " (цена ниже)"
            parts.append(f"MA20: {self.ma20}{rel}")
        if self.ma50 is not None:
            rel = ""
            if last_close is not None:
                rel = " (цена выше)" if last_close > self.ma50 else " (цена ниже)"
            parts.append(f"MA50: {self.ma50}{rel}")
        if self.volume_ratio is not None:
            parts.append(f"Объём 5д/30д: {self.volume_ratio}×")
        return ". ".join(parts) if parts else "Индикаторов недостаточно."


def _mean(values: list[Decimal]) -> Decimal:
    return (sum(values) / len(values)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def compute_indicators(candles: list[Candle]) -> Indicators:
    candles = sorted(candles, key=lambda c: c.day)
    closes = [c.close for c in candles]
    rsi = ma20 = ma50 = vol_ratio = None
    if len(closes) >= RSI_PERIOD + 1:
        diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - RSI_PERIOD, len(closes))]
        gains = sum(d for d in diffs if d > 0)
        losses = -sum(d for d in diffs if d < 0)
        if gains + losses == 0:
            rsi = Decimal("50.0")
        else:
            rsi = (gains / (gains + losses) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
    if len(closes) >= 20:
        ma20 = _mean(closes[-20:])
    if len(closes) >= 50:
        ma50 = _mean(closes[-50:])
    volumes = [Decimal(c.volume) for c in candles]
    if len(volumes) >= VOL_LONG:
        long_avg = sum(volumes[-VOL_LONG:]) / VOL_LONG
        short_avg = sum(volumes[-VOL_SHORT:]) / VOL_SHORT
        if long_avg:
            vol_ratio = (short_avg / long_avg).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return Indicators(rsi14=rsi, ma20=ma20, ma50=ma50, volume_ratio=vol_ratio)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/broker/tech.py tests/test_tech_indicators.py
git commit -m "feat: code-computed RSI/MA/volume indicators"
```

---

### Task 3: Дивиденды из Tinkoff + текстовая сводка

**Files:**
- Modify: `src/roaring_kittens/broker/models.py`, `src/roaring_kittens/broker/tinkoff_client.py`
- Create: `src/roaring_kittens/broker/fundamentals.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Падающий тест (pure-сводка)**

```python
# tests/test_fundamentals.py
from datetime import date
from decimal import Decimal

from roaring_kittens.broker.fundamentals import format_dividend_summary
from roaring_kittens.broker.models import DividendItem

TODAY = date(2026, 7, 12)


def test_no_dividends():
    text = format_dividend_summary([], last_close=Decimal("300"), today=TODAY)
    assert "не выплачивались" in text


def test_summary_with_yield_excludes_future_from_12m_sum():
    items = [
        DividendItem(payment_date=date(2025, 12, 10), amount=Decimal("15")),
        DividendItem(payment_date=date(2026, 6, 20), amount=Decimal("18")),
        DividendItem(payment_date=date(2026, 9, 20), amount=Decimal("20")),  # ОБЪЯВЛЕН, будущее
        DividendItem(payment_date=date(2023, 5, 1), amount=Decimal("10")),   # старше 12 мес
    ]
    text = format_dividend_summary(items, last_close=Decimal("300"), today=TODAY)
    assert "18 ₽" in text and "15 ₽" in text
    # за 12 мес ВЫПЛАЧЕНО: 15+18=33 (будущие 20 ₽ не считаются); 33/300*100 = 11.0%
    assert "33" in text and "11.0%" in text
    assert "Объявлено" in text and "20 ₽" in text  # будущая выплата показана отдельно


def test_summary_without_price_skips_yield():
    items = [DividendItem(payment_date=date(2026, 6, 20), amount=Decimal("18"))]
    text = format_dividend_summary(items, last_close=None, today=TODAY)
    assert "%" not in text


def test_only_announced_future_dividend():
    items = [DividendItem(payment_date=date(2026, 9, 20), amount=Decimal("20"))]
    text = format_dividend_summary(items, last_close=Decimal("300"), today=TODAY)
    assert "Объявлено" in text and "не выплачивались" not in text
```

- [ ] **Step 2: Реализовать**

В `broker/models.py` добавить:

```python
@dataclass(frozen=True)
class DividendItem:
    payment_date: date | None
    amount: Decimal
```

`broker/fundamentals.py`:

```python
# src/roaring_kittens/broker/fundamentals.py
"""Фундаментал v1 = дивиденды. Все числа считает код — LLM получает готовый текст."""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import DividendItem


def format_dividend_summary(items: list[DividendItem], last_close: Decimal | None,
                            today: date) -> str:
    dated = sorted([i for i in items if i.payment_date is not None],
                   key=lambda i: i.payment_date)
    paid = [i for i in dated if i.payment_date <= today]
    announced = [i for i in dated if i.payment_date > today]
    if not dated:
        return "Дивиденды за последние 3 года не выплачивались (или данных нет)."
    lines: list[str] = []
    if paid:
        lines.append("Дивиденды (последние выплаты):")
        for i in paid[-4:]:
            lines.append(f"- {i.payment_date:%d.%m.%Y}: {i.amount} ₽")
        year_ago = today - timedelta(days=365)
        last12 = sum((i.amount for i in paid if i.payment_date >= year_ago), Decimal("0"))
        if last12 > 0:
            line = f"Сумма за 12 мес: {last12} ₽"
            if last_close:
                y = (last12 / last_close * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
                line += f" (~{y}% доходности к текущей цене)"
            lines.append(line)
    for i in announced:
        lines.append(f"Объявлено (ещё не выплачено): {i.payment_date:%d.%m.%Y}: {i.amount} ₽")
    return "\n".join(lines)
```

В `broker/tinkoff_client.py` добавить метод (импорты `timedelta`, `money_to_decimal`, `now` уже есть):

```python
    @retry_async(attempts=3, base_delay=1.0)
    async def get_dividends(self, figi: str, years_back: int = 3) -> list[DividendItem]:
        async with AsyncClient(self._token) as client:
            resp = await client.instruments.get_dividends(
                figi=figi,
                from_=now() - timedelta(days=365 * years_back),
                to=now() + timedelta(days=365),  # включая объявленные будущие
            )
            return [
                DividendItem(
                    # SDK превращает незаданный protobuf-Timestamp в epoch(1970) —
                    # None он не бывает никогда, поэтому фильтруем по году.
                    payment_date=(d.payment_date.date()
                                  if d.payment_date and d.payment_date.year > 1970
                                  else None),
                    amount=money_to_decimal(d.dividend_net),
                )
                for d in resp.dividends
            ]
```

(добавить `DividendItem` в импорт из `roaring_kittens.broker.models`)

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/broker tests/test_fundamentals.py
git commit -m "feat: tinkoff dividends + code-computed dividend summary"
```

---

### Task 4: Позиция — pure-функции (рефакторинг из ask.py)

**Files:**
- Create: `src/roaring_kittens/broker/position_note.py`
- Modify: `src/roaring_kittens/telegram/handlers/ask.py`
- Test: `tests/test_position_note.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_position_note.py
from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.broker.position_note import (
    position_note_from_snapshot, position_weight_pct,
)

SNAP = PortfolioSnapshot(
    total_value=Decimal("1000000"),
    positions=[Position(ticker="SBER", name="Сбер", figi="F", quantity=Decimal("500"),
                        avg_price=Decimal("280"), current_price=Decimal("294"),
                        pnl_pct=Decimal("5.0"))],
)
EMPTY = PortfolioSnapshot(total_value=Decimal("0"), positions=[])


def test_note_for_held_position_has_qty_and_weight():
    note = position_note_from_snapshot(SNAP, "SBER")
    assert "500 шт по 280" in note and "14.7%" in note  # 500*294/1e6*100


def test_note_for_missing_position():
    assert "НЕТ" in position_note_from_snapshot(SNAP, "GAZP")


def test_weight_pct():
    assert position_weight_pct(SNAP, "SBER") == Decimal("14.7")
    assert position_weight_pct(SNAP, "GAZP") is None
    assert position_weight_pct(EMPTY, "SBER") is None  # пустой счёт — не делим на 0
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/broker/position_note.py
"""Pure-функции о позиции пользователя. IO (get_portfolio) остаётся у вызывающего."""
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import PortfolioSnapshot


def position_weight_pct(snap: PortfolioSnapshot, ticker: str) -> Decimal | None:
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None or not snap.total_value:
        return None
    return (pos.quantity * pos.current_price / snap.total_value * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)


def position_note_from_snapshot(snap: PortfolioSnapshot, ticker: str) -> str:
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None:
        return "Позиция: у пользователя НЕТ этой бумаги в портфеле."
    weight = position_weight_pct(snap, ticker) or Decimal("0")
    return (f"Позиция: {pos.quantity} шт по {pos.avg_price} ₽ "
            f"(P&L {pos.pnl_pct:+}%), вес {weight}% портфеля.")
```

В `ask.py` заменить тело `build_position_note` (импорт добавить, Decimal-импорт остаётся для других мест либо убрать если не нужен):

```python
from roaring_kittens.broker.position_note import position_note_from_snapshot

async def build_position_note(deps: Deps, ticker: str) -> str | None:
    """Блок о реальной позиции владельца. None при сбое (не блокируем разбор)."""
    try:
        snap = await deps.broker.get_portfolio()
    except Exception as exc:
        log.warning("position_note_failed", error=str(exc))
        return None
    return position_note_from_snapshot(snap, ticker)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/broker/position_note.py src/roaring_kittens/telegram/handlers/ask.py tests/test_position_note.py
git commit -m "refactor: pure position note/weight fns shared by ask and committee"
```

---

### Task 5: Схемы комитета

**Files:**
- Create: `src/roaring_kittens/committee/__init__.py` (пустой), `src/roaring_kittens/committee/schemas.py`

- [ ] **Step 1: Реализовать (schemas — декларативные, отдельные тесты не нужны; валидируются в тестах узлов)**

```python
# src/roaring_kittens/committee/schemas.py
from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["bullish", "bearish", "neutral"]


class SpecialistView(BaseModel):
    role: Literal["news", "technical", "fundamentals", "sentiment"]
    stance: Stance
    summary: str = Field(description="2-3 предложения: главный вывод по своей зоне")
    key_points: list[str] = Field(description="2-4 факта из предоставленных данных")
    confidence: float = Field(ge=0, le=1)


class DebateTurn(BaseModel):
    argument: str = Field(description="главный аргумент этого хода, 2-4 предложения")
    rebuttal_of: str = Field(description="какой тезис оппонента атакуешь (кратко)")
    position_after: Stance = Field(description="твоя позиция после этого хода")


class Proposal(BaseModel):
    action: Literal["buy", "sell", "hold", "wait"]
    stance: Stance
    rationale: str = Field(description="3-5 предложений: решение и почему")
    thesis: str = Field(description="однострочный тезис ставки")
    invalidation: str = Field(description="конкретный триггер, при котором тезис ломается")
    confidence: float = Field(ge=0, le=1)


class RiskReview(BaseModel):
    approved: bool
    veto_reason: str | None = None
    notes: list[str] = Field(default_factory=list, description="1-3 замечания по рискам")
```

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/committee
git commit -m "feat: committee pydantic schemas"
```

---

### Task 6: CouncilContext — сборка данных одним заходом

**Files:**
- Create: `src/roaring_kittens/committee/context.py`
- Modify: `tests/conftest.py` (общая фикстура `council_ctx` — НЕ импортировать между тест-модулями: tests/ не пакет, `from tests.test_X import ...` ломается вне `python -m pytest`)
- Test: `tests/test_council_context.py`

- [ ] **Step 0: Фикстура в tests/conftest.py (в конец файла)**

```python
@pytest.fixture
def council_ctx():
    """Минимальный контекст комитета: тонкие данные, пустой счёт, гость."""
    from decimal import Decimal

    from roaring_kittens.broker.tech import Indicators
    from roaring_kittens.committee.context import CouncilContext

    return CouncilContext(
        ticker="SBER", tech=None,
        indicators=Indicators(rsi14=Decimal("43.2"), ma20=None, ma50=None,
                              volume_ratio=None),
        news_facts=[], crowd_posts=[], dividend_summary="Дивиденды: нет данных.",
        position_note=None, position_weight_pct=None, prev_call_note=None)
```

- [ ] **Step 1: Падающий тест (monkeypatch модульных зависимостей)**

```python
# tests/test_council_context.py
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import roaring_kittens.committee.context as ctx_mod
from roaring_kittens.broker.models import Candle, PortfolioSnapshot
from roaring_kittens.committee.context import build_council_context
from roaring_kittens.news.models import NewsItem
from roaring_kittens.universe.universe import Instrument

INSTR = Instrument(ticker="SBER", figi="F", name="Сбер", aliases=frozenset())


def _news(source, headline):
    return NewsItem(source=source, url=f"https://x/{source}/{headline}", headline=headline,
                    body=None, published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])


class FakeSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class FakeBroker:
    async def get_daily_candles(self, figi, days=90):
        return [Candle(day=date(2026, 5, 1), open=Decimal(100), close=Decimal(100),
                       high=Decimal(101), low=Decimal(99), volume=1)] * 1

    async def get_dividends(self, figi, years_back=3):
        return []

    async def get_portfolio(self):
        return PortfolioSnapshot(total_value=Decimal("0"), positions=[])


async def test_build_context_splits_news_and_survives_empty_account(monkeypatch):
    async def fake_news(session, tickers, since, limit=50):
        return [_news("rbc", "факт"), _news("smartlab", "мнение")]

    async def fake_last_call(session, ticker, within_days=7):
        return None

    async def fake_owner(session_factory):
        return 42

    monkeypatch.setattr(ctx_mod, "get_news_for_tickers", fake_news)
    monkeypatch.setattr(ctx_mod, "get_last_call", fake_last_call)
    monkeypatch.setattr(ctx_mod, "fetch_owner_id", fake_owner)
    deps = SimpleNamespace(broker=FakeBroker(), session_factory=lambda: FakeSession())

    ctx = await build_council_context(deps, INSTR, asked_by=42, today=date(2026, 7, 12))
    assert [n.headline for n in ctx.news_facts] == ["факт"]
    assert [n.headline for n in ctx.crowd_posts] == ["мнение"]
    assert ctx.tech is None                       # 1 свеча < MIN_CANDLES
    assert ctx.position_weight_pct is None        # пустой счёт
    assert "НЕТ" in ctx.position_note             # владелец, но бумаги нет
    assert "не выплачивались" in ctx.dividend_summary
    assert ctx.prev_call_note is None
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/context.py
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog

from roaring_kittens.broker.fundamentals import format_dividend_summary
from roaring_kittens.broker.position_note import (
    position_note_from_snapshot, position_weight_pct,
)
from roaring_kittens.broker.tech import Indicators, TechSummary, compute_indicators, compute_tech_summary
from roaring_kittens.db.calls import get_last_call
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()

NEWS_WINDOW_DAYS = 7
CANDLES_DAYS = 90
CROWD_SOURCES = {"smartlab"}


@dataclass
class CouncilContext:
    ticker: str
    tech: TechSummary | None
    indicators: Indicators
    news_facts: list[NewsItem]
    crowd_posts: list[NewsItem]
    dividend_summary: str
    position_note: str | None          # None => спрашивал не владелец
    position_weight_pct: Decimal | None
    prev_call_note: str | None


async def build_council_context(deps, instrument: Instrument, asked_by: int,
                                today: date) -> CouncilContext:
    candles = await deps.broker.get_daily_candles(instrument.figi, days=CANDLES_DAYS)
    tech = compute_tech_summary(candles)
    indicators = compute_indicators(candles)

    since = datetime.now(tz=timezone.utc) - timedelta(days=NEWS_WINDOW_DAYS)
    async with deps.session_factory() as session:
        news = await get_news_for_tickers(session, [instrument.ticker], since=since)
        prev = await get_last_call(session, instrument.ticker)
    facts = [n for n in news if n.source not in CROWD_SOURCES]
    crowd = [n for n in news if n.source in CROWD_SOURCES]

    try:
        divs = await deps.broker.get_dividends(instrument.figi)
    except Exception as exc:
        log.warning("dividends_failed", ticker=instrument.ticker, error=str(exc))
        divs = []
    dividend_summary = format_dividend_summary(
        divs, tech.last_close if tech else None, today=today)

    position_note, weight = None, None
    owner_id = await fetch_owner_id(deps.session_factory)
    if asked_by == owner_id:
        try:
            snap = await deps.broker.get_portfolio()
            position_note = position_note_from_snapshot(snap, instrument.ticker)
            weight = position_weight_pct(snap, instrument.ticker)
        except Exception as exc:
            log.warning("council_position_failed", error=str(exc))

    prev_note = None
    if prev:
        days = (datetime.now(tz=timezone.utc) - prev.created_at).days
        prev_note = (f"Прошлый разбор бота ({days} дн назад): "
                     f"{prev.stance} {round(prev.confidence * 100)}%")

    return CouncilContext(ticker=instrument.ticker, tech=tech, indicators=indicators,
                          news_facts=facts, crowd_posts=crowd,
                          dividend_summary=dividend_summary,
                          position_note=position_note, position_weight_pct=weight,
                          prev_call_note=prev_note)
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/context.py tests/test_council_context.py
git commit -m "feat: council context assembly (tech+indicators, news split, dividends, position)"
```

---

### Task 7: Четыре специалиста (параллельно)

**Files:**
- Create: `src/roaring_kittens/committee/specialists.py`
- Test: `tests/test_specialists.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_specialists.py
from roaring_kittens.committee.schemas import SpecialistView
from roaring_kittens.committee.specialists import ROLE_PROMPTS, build_specialist_user, run_specialists


class FakeLLM:
    def __init__(self):
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append(operation)
        return SpecialistView(role="news", stance="neutral", summary="s",
                              key_points=["k"], confidence=0.5)


async def test_runs_all_four_roles_and_fixes_role_field(council_ctx):
    llm = FakeLLM()
    views = await run_specialists(llm, council_ctx)
    assert sorted(v.role for v in views) == ["fundamentals", "news", "sentiment", "technical"]
    assert sorted(llm.ops) == ["council_fundamentals", "council_news",
                               "council_sentiment", "council_technical"]


def test_each_role_gets_its_data_slice(council_ctx):
    assert "RSI(14): 43.2" in build_specialist_user(council_ctx, "technical")
    assert "Дивиденды" in build_specialist_user(council_ctx, "fundamentals")
    assert "новостей нет" in build_specialist_user(council_ctx, "news").lower()
    assert "постов нет" in build_specialist_user(council_ctx, "sentiment").lower()
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/specialists.py
import asyncio

from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import SpecialistView
from roaring_kittens.news.models import NewsItem

SPECIALIST_MODEL = "gpt-4o"

_COMMON = """Ты — узкий специалист инвесткомитета по Мосбирже. Отвечай ТОЛЬКО по своей зоне.
Опирайся ТОЛЬКО на предоставленные данные; не выдумывай числа и события.
Если данных мало — честно скажи и ставь низкую confidence. Пиши по-русски, кратко."""

ROLE_PROMPTS: dict[str, str] = {
    "news": _COMMON + "\nТвоя зона: корпоративные и рыночные СОБЫТИЯ (факты из новостей).",
    "technical": _COMMON + "\nТвоя зона: цена, тренд, уровни, индикаторы (числа даны кодом).",
    "fundamentals": _COMMON + "\nТвоя зона: дивиденды и фундаментальная привлекательность.",
    "sentiment": _COMMON + "\nТвоя зона: настроения розничной толпы (посты Smart-Lab); учитывай контрарианскую логику: эйфория толпы — тревожный знак.",
}


def _news_block(items: list[NewsItem], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(f"- [{n.published_at:%d.%m}] {n.headline}" for n in items[:10])


def build_specialist_user(ctx: CouncilContext, role: str) -> str:
    tech_text = ctx.tech.as_text() if ctx.tech else "Технических данных недостаточно."
    base = f"Тикер: {ctx.ticker}\nТехника: {tech_text}\n"
    if role == "news":
        return base + "\nНовости (7 дней):\n" + _news_block(ctx.news_facts, "Свежих новостей нет.")
    if role == "technical":
        return base + f"\nИндикаторы: {ctx.indicators.as_text(ctx.tech.last_close if ctx.tech else None)}"
    if role == "fundamentals":
        return base + f"\n{ctx.dividend_summary}"
    return base + "\nПосты Smart-Lab (7 дней):\n" + _news_block(ctx.crowd_posts, "Постов нет.")


async def run_specialist(llm, ctx: CouncilContext, role: str) -> SpecialistView:
    view = await llm.parse(
        model=SPECIALIST_MODEL, operation=f"council_{role}",
        messages=[{"role": "system", "content": ROLE_PROMPTS[role]},
                  {"role": "user", "content": build_specialist_user(ctx, role)}],
        schema=SpecialistView)
    return view.model_copy(update={"role": role})  # роль фиксируем кодом, не доверяем LLM


async def run_specialists(llm, ctx: CouncilContext) -> list[SpecialistView]:
    return list(await asyncio.gather(*(run_specialist(llm, ctx, r) for r in ROLE_PROMPTS)))
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/specialists.py tests/test_specialists.py
git commit -m "feat: four parallel committee specialists with per-role data slices"
```

---

### Task 8: Bull/Bear дебаты

**Files:**
- Create: `src/roaring_kittens/committee/debate.py`
- Test: `tests/test_debate.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_debate.py
from roaring_kittens.committee.debate import build_debate_user, is_converged, run_debate_turn
from roaring_kittens.committee.schemas import DebateTurn, SpecialistView

VIEWS = [SpecialistView(role="news", stance="neutral", summary="s",
                        key_points=["k"], confidence=0.5)]


def _turn(speaker, position):
    return {"speaker": speaker, "argument": "a", "rebuttal_of": "-",
            "position_after": position}


def test_convergence_when_positions_match():
    assert is_converged([_turn("bull", "neutral"), _turn("bear", "neutral")]) is True
    assert is_converged([_turn("bull", "bullish"), _turn("bear", "bearish")]) is False
    assert is_converged([_turn("bull", "bullish")]) is False  # bear ещё не ходил


def test_debate_user_contains_views_and_history(council_ctx):
    text = build_debate_user(council_ctx, VIEWS, [_turn("bull", "bullish")], "bear")
    assert "news" in text and "БЫК" in text.upper()


class FakeLLM:
    def __init__(self):
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append((operation, model))
        return DebateTurn(argument="a", rebuttal_of="-", position_after="bullish")


async def test_turn_uses_o4_mini_and_role_op(council_ctx):
    llm = FakeLLM()
    turn = await run_debate_turn(llm, council_ctx, VIEWS, [], "bull")
    assert turn.position_after == "bullish"
    assert llm.ops == [("council_debate_bull", "o4-mini")]
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/debate.py
from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import DebateTurn, SpecialistView

DEBATE_MODEL = "o4-mini"
MAX_ROUNDS = 3

BULL_SYSTEM = """Ты — Bull Researcher инвесткомитета. Твоя работа — построить СИЛЬНЕЙШИЙ
аргумент ЗА покупку/удержание, даже если данные неоднозначны. Не уклоняйся в нейтральность —
взвешивать будет Portfolio Manager. Атакуй конкретные тезисы оппонента. Опирайся только на
данные комитета, не выдумывай. Если после дебатов честно признаёшь правоту оппонента —
можешь сменить position_after. По-русски, кратко."""

BEAR_SYSTEM = """Ты — Bear Researcher инвесткомитета. Твоя работа — найти риски и построить
СИЛЬНЕЙШИЙ аргумент ПРОТИВ, даже если данные неоднозначны. Не уклоняйся в нейтральность —
взвешивать будет Portfolio Manager. Атакуй конкретные тезисы оппонента. Опирайся только на
данные комитета, не выдумывай. Если после дебатов честно признаёшь правоту оппонента —
можешь сменить position_after. По-русски, кратко."""


def build_debate_user(ctx: CouncilContext, views: list[SpecialistView],
                      debate_log: list[dict], speaker: str) -> str:
    parts = [f"Тикер: {ctx.ticker}", "", "Мнения специалистов:"]
    for v in views:
        parts.append(f"- {v.role} ({v.stance}, {round(v.confidence*100)}%): {v.summary}")
    if ctx.position_note:
        parts.append(f"\n{ctx.position_note}")
    if ctx.prev_call_note:
        parts.append(ctx.prev_call_note)
    if debate_log:
        parts.append("\nХод дебатов:")
        for t in debate_log:
            who = "БЫК" if t["speaker"] == "bull" else "МЕДВЕДЬ"
            parts.append(f"[{who} → {t['position_after']}] {t['argument']}")
    parts.append(f"\nТвой ход ({'бык' if speaker == 'bull' else 'медведь'}).")
    return "\n".join(parts)


async def run_debate_turn(llm, ctx: CouncilContext, views: list[SpecialistView],
                          debate_log: list[dict], speaker: str) -> DebateTurn:
    system = BULL_SYSTEM if speaker == "bull" else BEAR_SYSTEM
    return await llm.parse(
        model=DEBATE_MODEL, operation=f"council_debate_{speaker}",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": build_debate_user(ctx, views, debate_log, speaker)}],
        schema=DebateTurn)


def is_converged(debate_log: list[dict]) -> bool:
    """Сошлись, если последние позиции быка и медведя совпали."""
    last = {}
    for t in debate_log:
        last[t["speaker"]] = t["position_after"]
    return len(last) == 2 and last["bull"] == last["bear"]
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/debate.py tests/test_debate.py
git commit -m "feat: adversarial bull/bear debate turns with convergence check"
```

---

### Task 9: Portfolio Manager + Risk Manager

**Files:**
- Create: `src/roaring_kittens/committee/manager.py`, `src/roaring_kittens/committee/risk.py`
- Test: `tests/test_manager_risk.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_manager_risk.py
from dataclasses import replace
from decimal import Decimal

from roaring_kittens.committee.manager import run_manager
from roaring_kittens.committee.risk import hard_checks, run_risk
from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView

VIEWS = [SpecialistView(role="news", stance="neutral", summary="s",
                        key_points=["k"], confidence=0.5)]
PROPOSAL = Proposal(action="buy", stance="bullish", rationale="r", thesis="t",
                    invalidation="цена ниже 250", confidence=0.7)


def test_hard_checks_concentration_veto(council_ctx):
    fat = replace(council_ctx, position_weight_pct=Decimal("16"))
    vetoes = hard_checks(fat, PROPOSAL)
    assert any("Концентрация" in v for v in vetoes)
    # sell при большой позиции — концентрационного вето нет; берём confidence<=0.6,
    # чтобы не сработало И overconfidence-вето (ctx.tech is None). Оно намеренно
    # применяется к ЛЮБОМУ action — переуверенный sell так же вреден.
    sell = PROPOSAL.model_copy(update={"action": "sell", "confidence": 0.5})
    assert hard_checks(fat, sell) == []


def test_hard_checks_overconfidence_on_thin_data(council_ctx):
    vetoes = hard_checks(council_ctx, PROPOSAL)  # tech None, confidence 0.7 > 0.6
    assert any("тонких данных" in v for v in vetoes)


def test_hard_checks_empty_account_no_weight_veto(council_ctx):
    assert not any("Концентрация" in v
                   for v in hard_checks(council_ctx, PROPOSAL))  # weight None -> пропуск


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append((operation, model))
        return self.result


async def test_manager_op_and_model(council_ctx):
    llm = FakeLLM(PROPOSAL)
    p = await run_manager(llm, council_ctx, VIEWS, [])
    assert p.action == "buy"
    assert llm.ops == [("council_manager", "gpt-4o")]


async def test_risk_hard_veto_overrides_llm_approval(council_ctx):
    llm = FakeLLM(RiskReview(approved=True, veto_reason=None, notes=["ok"]))
    review = await run_risk(llm, council_ctx, PROPOSAL, vetoes=["Концентрация: 16%"])
    assert review.approved is False and "Концентрация" in review.veto_reason
    assert llm.ops[0] == ("council_risk", "o4-mini")


async def test_risk_llm_veto_respected(council_ctx):
    llm = FakeLLM(RiskReview(approved=False, veto_reason="волатильность", notes=[]))
    review = await run_risk(llm, council_ctx, PROPOSAL, vetoes=[])
    assert review.approved is False and review.veto_reason == "волатильность"
```

- [ ] **Step 2: Реализовать manager.py**

```python
# src/roaring_kittens/committee/manager.py
from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import Proposal, SpecialistView

PM_MODEL = "gpt-4o"

PM_SYSTEM = """Ты — Portfolio Manager инвесткомитета. Ты не бык и не медведь — ты прагматик.
Перед тобой мнения 4 специалистов и протокол дебатов Bull vs Bear. Прими решение в интересах
пользователя. Если уверенности нет — выбирай wait. Если позиции пользователя нет или счёт
пуст — это «режим идей»: action=buy означает идею на покупку, БЕЗ размера позиции.
thesis — одна строка, invalidation — конкретный проверяемый триггер. По-русски, кратко."""


def build_manager_user(ctx: CouncilContext, views: list[SpecialistView],
                       debate_log: list[dict]) -> str:
    parts = [f"Тикер: {ctx.ticker}",
             f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}",
             "", "Мнения специалистов:"]
    for v in views:
        parts.append(f"- {v.role} ({v.stance}, {round(v.confidence*100)}%): {v.summary}")
    parts.append("\nПротокол дебатов:")
    if debate_log:
        for t in debate_log:
            who = "БЫК" if t["speaker"] == "bull" else "МЕДВЕДЬ"
            parts.append(f"[{who} → {t['position_after']}] {t['argument']}")
    else:
        parts.append("(дебатов не было)")
    if ctx.position_note:
        parts.append(f"\n{ctx.position_note}")
    if ctx.prev_call_note:
        parts.append(ctx.prev_call_note)
    return "\n".join(parts)


async def run_manager(llm, ctx: CouncilContext, views: list[SpecialistView],
                      debate_log: list[dict]) -> Proposal:
    return await llm.parse(
        model=PM_MODEL, operation="council_manager",
        messages=[{"role": "system", "content": PM_SYSTEM},
                  {"role": "user", "content": build_manager_user(ctx, views, debate_log)}],
        schema=Proposal)
```

- [ ] **Step 3: Реализовать risk.py**

```python
# src/roaring_kittens/committee/risk.py
from decimal import Decimal

from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import Proposal, RiskReview

RISK_MODEL = "o4-mini"
MAX_POSITION_WEIGHT_PP = Decimal("15")
OVERCONFIDENCE_THRESHOLD = 0.6

RISK_SYSTEM = """Ты — Risk Manager инвесткомитета с правом вето. Ты не оцениваешь идею —
ты защищаешь пользователя от неприемлемого риска. Результаты жёстких проверок кода даны
тебе как факт. Вето — только с конкретной причиной в одно предложение. По-русски."""


def hard_checks(ctx: CouncilContext, proposal: Proposal) -> list[str]:
    """Детерминированные проверки кодом. Непустой список = безусловное вето."""
    vetoes: list[str] = []
    if (proposal.action == "buy" and ctx.position_weight_pct is not None
            and ctx.position_weight_pct >= MAX_POSITION_WEIGHT_PP):
        vetoes.append(f"Концентрация: уже {ctx.position_weight_pct}% портфеля "
                      f"(лимит {MAX_POSITION_WEIGHT_PP}%)")
    if ctx.tech is None and proposal.confidence > OVERCONFIDENCE_THRESHOLD:
        vetoes.append("Переуверенность на тонких данных: нет техники, "
                      f"а confidence {round(proposal.confidence*100)}%")
    return vetoes


def build_risk_user(ctx: CouncilContext, proposal: Proposal, vetoes: list[str]) -> str:
    parts = [f"Тикер: {ctx.ticker}",
             f"Предложение PM: {proposal.action} ({proposal.stance}, "
             f"{round(proposal.confidence*100)}%)",
             f"Тезис: {proposal.thesis}",
             f"Инвалидация: {proposal.invalidation}",
             f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}"]
    if ctx.position_note:
        parts.append(ctx.position_note)
    parts.append("Жёсткие проверки кода: " + ("; ".join(vetoes) if vetoes else "пройдены"))
    return "\n".join(parts)


async def run_risk(llm, ctx: CouncilContext, proposal: Proposal,
                   vetoes: list[str]) -> RiskReview:
    llm_review: RiskReview = await llm.parse(
        model=RISK_MODEL, operation="council_risk",
        messages=[{"role": "system", "content": RISK_SYSTEM},
                  {"role": "user", "content": build_risk_user(ctx, proposal, vetoes)}],
        schema=RiskReview)
    if vetoes:  # hard-вето кода не переспоришь
        return RiskReview(approved=False, veto_reason="; ".join(vetoes),
                          notes=llm_review.notes)
    return llm_review
```

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/committee/manager.py src/roaring_kittens/committee/risk.py tests/test_manager_risk.py
git commit -m "feat: portfolio manager and risk manager with deterministic hard vetoes"
```

---

### Task 10: LangGraph — сборка графа

**Files:**
- Create: `src/roaring_kittens/committee/graph.py`
- Test: `tests/test_council_graph.py`

- [ ] **Step 1: Падающий тест (e2e на FakeLLM)**

```python
# tests/test_council_graph.py
from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.schemas import DebateTurn, Proposal, RiskReview, SpecialistView


class ScriptedLLM:
    """bull всегда bullish; bear: 1-й ход bearish, 2-й — сдаётся в bullish (сходимость на 2 раунде)."""

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


async def test_graph_runs_end_to_end_with_early_convergence(council_ctx):
    llm = ScriptedLLM()
    graph = build_council_graph(llm)
    state = await graph.ainvoke({"ctx": council_ctx})
    assert state["proposal"].action == "wait"
    assert state["risk"].approved is True
    assert len(state["views"]) == 4
    # 2 раунда дебатов (bear сдался на втором) => 4 хода, не 6
    assert len(state["debate"]) == 4
    assert state["round"] == 2
    # порядок: 4 специалиста -> дебаты -> manager -> risk
    assert llm.ops[-2:] == ["council_manager", "council_risk"]
    assert llm.ops.count("council_debate_bull") == 2
    assert llm.ops.count("council_debate_bear") == 2
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/graph.py
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged, run_debate_turn
from roaring_kittens.committee.manager import run_manager
from roaring_kittens.committee.risk import hard_checks, run_risk
from roaring_kittens.committee.specialists import run_specialists


class CouncilState(TypedDict, total=False):
    ctx: Any
    views: list
    debate: list
    round: int
    proposal: Any
    risk: Any


def build_council_graph(llm):
    async def specialists_node(state: CouncilState):
        views = await run_specialists(llm, state["ctx"])
        return {"views": views, "debate": [], "round": 0}

    async def bull_node(state: CouncilState):
        turn = await run_debate_turn(llm, state["ctx"], state["views"],
                                     state["debate"], "bull")
        return {"debate": state["debate"] + [{"speaker": "bull", **turn.model_dump()}]}

    async def bear_node(state: CouncilState):
        turn = await run_debate_turn(llm, state["ctx"], state["views"],
                                     state["debate"], "bear")
        return {"debate": state["debate"] + [{"speaker": "bear", **turn.model_dump()}],
                "round": state["round"] + 1}

    def after_bear(state: CouncilState) -> str:
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return "manager"
        return "bull"

    async def manager_node(state: CouncilState):
        proposal = await run_manager(llm, state["ctx"], state["views"], state["debate"])
        return {"proposal": proposal}

    async def risk_node(state: CouncilState):
        vetoes = hard_checks(state["ctx"], state["proposal"])
        review = await run_risk(llm, state["ctx"], state["proposal"], vetoes)
        return {"risk": review}

    g = StateGraph(CouncilState)
    g.add_node("specialists", specialists_node)
    g.add_node("bull", bull_node)
    g.add_node("bear", bear_node)
    g.add_node("manager", manager_node)
    g.add_node("risk", risk_node)
    g.add_edge(START, "specialists")
    g.add_edge("specialists", "bull")
    g.add_edge("bull", "bear")
    g.add_conditional_edges("bear", after_bear, {"bull": "bull", "manager": "manager"})
    g.add_edge("manager", "risk")
    g.add_edge("risk", END)
    return g.compile()
```

- [ ] **Step 3: Push → CI (Tasks 1–10), Commit**

```bash
git add src/roaring_kittens/committee/graph.py tests/test_council_graph.py
git commit -m "feat: langgraph council pipeline with debate loop and early exit"
```

---

### Task 11: Хранение транскриптов (council_runs)

**Files:**
- Modify: `db/schema.sql`, `src/roaring_kittens/db/tables.py`, `tests/conftest.py`
- Create: `src/roaring_kittens/db/council.py`
- Test: `tests/test_council_repo.py`

- [ ] **Step 1: Схема (schema.sql, перед bot_state)**

```sql
CREATE TABLE IF NOT EXISTS council_runs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ticker     VARCHAR(20) NOT NULL,
    asked_by   BIGINT NOT NULL,
    transcript JSONB NOT NULL,
    call_id    UUID REFERENCES calls(id)
);
```

`tables.py` (JSONB импортировать из sqlalchemy.dialects.postgresql):

```python
council_runs = Table(
    "council_runs", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("ticker", String(20), nullable=False),
    Column("asked_by", BigInteger, nullable=False),
    Column("transcript", JSONB, nullable=False),
    Column("call_id", UUID(as_uuid=True), ForeignKey("calls.id")),
)
```

`conftest.py`: `TRUNCATE news_events, usage_log, bot_state, council_runs, call_scores, calls`

- [ ] **Step 2: Падающий тест**

```python
# tests/test_council_repo.py
import os

import pytest

from roaring_kittens.db.council import get_council_transcript, save_council_run

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_save_and_get_transcript(db_session_factory):
    transcript = {"views": [{"role": "news"}], "debate": [], "proposal": {"action": "wait"}}
    async with db_session_factory() as session:
        run_id = await save_council_run(session, ticker="SBER", asked_by=42,
                                        transcript=transcript, call_id=None)
        await session.commit()
    async with db_session_factory() as session:
        loaded = await get_council_transcript(session, run_id)
        assert loaded["proposal"]["action"] == "wait"
        assert await get_council_transcript(session, run_id=None) is None
```

- [ ] **Step 3: Реализовать**

```python
# src/roaring_kittens/db/council.py
from uuid import UUID as UUIDType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roaring_kittens.db.tables import council_runs


async def save_council_run(session: AsyncSession, *, ticker: str, asked_by: int,
                           transcript: dict, call_id: UUIDType | None) -> UUIDType:
    result = await session.execute(
        council_runs.insert().values(ticker=ticker, asked_by=asked_by,
                                     transcript=transcript, call_id=call_id)
        .returning(council_runs.c.id))
    return result.scalar_one()


async def get_council_transcript(session: AsyncSession,
                                 run_id: UUIDType | None) -> dict | None:
    if run_id is None:
        return None
    row = (await session.execute(
        select(council_runs.c.transcript).where(council_runs.c.id == run_id))).first()
    return row[0] if row else None
```

- [ ] **Step 4: Commit**

```bash
git add db/schema.sql src/roaring_kittens/db tests/conftest.py tests/test_council_repo.py
git commit -m "feat: council_runs transcript storage"
```

---

### Task 12: Рендер вердикта и протокола

**Files:**
- Create: `src/roaring_kittens/committee/render.py`
- Test: `tests/test_council_render.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_council_render.py
from roaring_kittens.committee.render import chunk_lines, format_council_protocol, format_council_verdict
from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView

VIEWS = [SpecialistView(role="news", stance="bearish", summary="плохие новости",
                        key_points=["k"], confidence=0.6),
         SpecialistView(role="technical", stance="bullish", summary="отскок",
                        key_points=["k"], confidence=0.7)]
DEBATE = [{"speaker": "bull", "argument": "за рост", "rebuttal_of": "-",
           "position_after": "bullish"},
          {"speaker": "bear", "argument": "против", "rebuttal_of": "-",
           "position_after": "bearish"}]
PROPOSAL = Proposal(action="wait", stance="neutral", rationale="ждём отчёта",
                    thesis="тезис", invalidation="цена ниже 250", confidence=0.55)


def test_verdict_contains_action_thesis_and_votes():
    text = format_council_verdict("SBER", VIEWS, DEBATE, PROPOSAL,
                                  RiskReview(approved=True, notes=[]))
    assert "SBER" in text and "ждать" in text.lower()
    assert "тезис" in text and "цена ниже 250" in text
    assert "📰" in text and "📈" in text          # иконки ролей
    assert "1 раунд" in text


def test_verdict_shows_veto():
    text = format_council_verdict("SBER", VIEWS, DEBATE, PROPOSAL,
                                  RiskReview(approved=False, veto_reason="концентрация"))
    assert "⛔️" in text and "концентрация" in text


def test_protocol_chunks_under_limit():
    chunks = format_council_protocol(VIEWS, DEBATE, PROPOSAL,
                                     RiskReview(approved=True, notes=["n"]))
    assert all(len(c) <= 3500 for c in chunks)
    assert "плохие новости" in chunks[0]


def test_chunk_lines_splits():
    chunks = chunk_lines(["x" * 100] * 50, limit=1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks)


def test_chunk_lines_hard_splits_single_overlong_line():
    chunks = chunk_lines(["x" * 5000], limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert sum(len(c) for c in chunks) == 5000
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/committee/render.py
from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView
from roaring_kittens.telegram.formatting import STANCE_EMOJI

ACTION_RU = {"buy": "покупать", "sell": "продавать", "hold": "держать", "wait": "ждать"}
ROLE_ICON = {"news": "📰", "technical": "📈", "fundamentals": "💰", "sentiment": "🗣"}


def format_council_verdict(ticker: str, views: list[SpecialistView], debate: list[dict],
                           proposal: Proposal, risk: RiskReview) -> str:
    rounds = sum(1 for t in debate if t["speaker"] == "bear")
    votes = " · ".join(f"{ROLE_ICON[v.role]} {STANCE_EMOJI[v.stance]}" for v in views)
    risk_line = "🛡 Risk: ✅ одобрено" if risk.approved \
        else f"🛡 Risk: ⛔️ ВЕТО — {risk.veto_reason}"
    lines = [
        f"🏛 <b>Комитет по {ticker}</b> — {STANCE_EMOJI[proposal.stance]} "
        f"<b>{ACTION_RU[proposal.action]}</b> "
        f"(уверенность {round(proposal.confidence * 100)}%)",
        "",
        proposal.rationale,
        "",
        f"🎯 Тезис: {proposal.thesis}",
        f"🚨 Инвалидация: {proposal.invalidation}",
        "",
        f"Голоса: {votes} · дебаты: {rounds} раунд(а)",
        risk_line,
        "",
        "<i>Это аналитический разбор, не инвестрекомендация.</i>",
    ]
    return "\n".join(lines)


def format_council_protocol(views: list[SpecialistView], debate: list[dict],
                            proposal: Proposal, risk: RiskReview) -> list[str]:
    lines = ["📜 <b>Протокол комитета</b>", ""]
    for v in views:
        lines.append(f"{ROLE_ICON[v.role]} <b>{v.role}</b> — {STANCE_EMOJI[v.stance]} "
                     f"{v.stance} ({round(v.confidence*100)}%)")
        lines.append(v.summary)
        lines += [f"• {p}" for p in v.key_points]
        lines.append("")
    lines.append("⚔️ <b>Дебаты:</b>")
    for t in debate:
        who = "🐂 БЫК" if t["speaker"] == "bull" else "🐻 МЕДВЕДЬ"
        lines.append(f"{who} (→ {t['position_after']}): {t['argument']}")
    lines.append("")
    lines.append(f"👔 <b>PM:</b> {proposal.rationale}")
    if risk.notes:
        lines.append("🛡 Risk-заметки: " + "; ".join(risk.notes))
    return chunk_lines(lines)


def chunk_lines(lines: list[str], limit: int = 3500) -> list[str]:
    chunks, cur = [], ""

    def push(segment: str) -> None:
        nonlocal cur
        if cur and len(cur) + len(segment) + 1 > limit:
            chunks.append(cur)
            cur = segment
        else:
            cur = f"{cur}\n{segment}" if cur else segment

    for line in lines:
        while len(line) > limit:  # одна сверхдлинная строка не должна пробить лимит TG
            push(line[:limit])
            line = line[limit:]
        push(line)
    if cur:
        chunks.append(cur)
    return chunks
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/committee/render.py tests/test_council_render.py
git commit -m "feat: council verdict and chunked protocol rendering"
```

---

### Task 13: Handler /council + прогресс + запись в calls

**Files:**
- Create: `src/roaring_kittens/telegram/handlers/council.py`
- Modify: `src/roaring_kittens/telegram/handlers/__init__.py`, `src/roaring_kittens/telegram/handlers/start.py`

- [ ] **Step 1: Реализовать handler**

```python
# src/roaring_kittens/telegram/handlers/council.py
from datetime import date
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from roaring_kittens.committee.context import build_council_context
from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.render import format_council_protocol, format_council_verdict
from roaring_kittens.db.calls import save_call
from roaring_kittens.db.council import get_council_transcript, save_council_run
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/council SBER</code> — полный разбор комитетом (4 аналитика + дебаты)."


def _next_stage_text(node: str, state: dict, ticker: str) -> str | None:
    """astream(stream_mode='updates') стреляет ПОСЛЕ узла — анонсируем СЛЕДУЮЩУЮ стадию."""
    from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged
    if node == "specialists":
        return f"⚔️ {ticker}: аналитики высказались — дебаты Bull vs Bear…"
    if node == "bear":
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return f"👔 {ticker}: дебаты завершены — Portfolio Manager взвешивает…"
        return f"⚔️ {ticker}: дебаты, раунд {state['round'] + 1}…"
    if node == "manager":
        return f"🛡 {ticker}: Risk Manager проверяет…"
    return None


@router.message(Command("council"))
async def cmd_council(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer("🏛 Комитет пока доступен только владельцу — "
                             "тебе доступен /ask ТИКЕР.")
        return
    if not command.args:
        await message.answer(USAGE)
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}». {USAGE}")
        return

    progress = await message.answer(
        f"🏛 Собираю комитет по {instrument.ticker}… (4 аналитика изучают данные)")
    try:
        ctx = await build_council_context(deps, instrument, message.from_user.id,
                                          today=date.today())
        graph = build_council_graph(deps.llm)
        state = {"ctx": ctx}
        async for chunk in graph.astream(state, stream_mode="updates"):
            for node, update in chunk.items():
                state.update(update)
                stage = _next_stage_text(node, state, instrument.ticker)
                if stage:
                    try:
                        await progress.edit_text(stage)
                    except Exception:  # too-fast identical edits — не критично
                        pass
        proposal, risk = state["proposal"], state["risk"]
    except Exception as exc:
        log.error("council_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Комитет по {instrument.ticker} сорвался — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/council {instrument.ticker}</code>")
        return

    call_id = run_id = None
    try:  # персист не должен ронять ответ
        async with deps.session_factory() as session:
            # Вето Risk = комитет НЕ дал рекомендацию → в track-record не пишем
            # (иначе заблокированная идея скорилась бы как реальная ставка).
            if risk.approved:
                call_id = await save_call(
                    session, asked_by=message.from_user.id, ticker=instrument.ticker,
                    figi=instrument.figi, source="council", question=None,
                    stance=proposal.stance, confidence=proposal.confidence,
                    summary=proposal.rationale,
                    price_at_call=ctx.tech.last_close if ctx.tech else None,
                    news_urls=[n.url for n in ctx.news_facts + ctx.crowd_posts])
            transcript = {
                "views": [v.model_dump() for v in state["views"]],
                "debate": state["debate"],
                "proposal": proposal.model_dump(),
                "risk": risk.model_dump(),
            }
            run_id = await save_council_run(session, ticker=instrument.ticker,
                                            asked_by=message.from_user.id,
                                            transcript=transcript, call_id=call_id)
            await session.commit()
    except Exception as exc:
        log.error("council_persist_failed", ticker=instrument.ticker, error=str(exc))

    keyboard = None
    if run_id is not None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📜 Протокол", callback_data=f"proto:{run_id}")]])
    await progress.edit_text(
        format_council_verdict(instrument.ticker, state["views"], state["debate"],
                               proposal, risk),
        reply_markup=keyboard)


@router.callback_query(F.data.startswith("proto:"))
async def cb_protocol(callback: CallbackQuery, deps: Deps) -> None:
    # Owner-гейт обязателен: в транскрипте (rationale/дебаты) может фигурировать
    # позиция владельца — гостям это видеть нельзя.
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Протокол доступен только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.message.answer("Протокол не найден.")
        return
    async with deps.session_factory() as session:
        transcript = await get_council_transcript(session, run_id)
    if transcript is None:
        await callback.message.answer("Протокол не найден.")
        return
    from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView
    views = [SpecialistView(**v) for v in transcript["views"]]
    proposal = Proposal(**transcript["proposal"])
    risk = RiskReview(**transcript["risk"])
    for chunk in format_council_protocol(views, transcript["debate"], proposal, risk):
        await callback.message.answer(chunk)
```

- [ ] **Step 2: Wiring**

`handlers/__init__.py`:

```python
from roaring_kittens.telegram.handlers import ask, council, digest, portfolio, seed, start, track
...
all_routers.include_router(council.router)
```

`start.py` HELP_TEXT — в блок владельца добавить:

```python
    "• <code>/council ТИКЕР</code> — полный разбор комитетом (4 аналитика + дебаты)\n"
```

- [ ] **Step 3: Push → CI зелёный, Commit**

```bash
git add src/roaring_kittens/telegram
git commit -m "feat: /council command with staged progress, transcript button, calls logging"
```

---

### Task 14: README, деплой, E2E

- [ ] **Step 1: README — раздел «Комитет (Phase 2)» после Trust Loop**

```markdown
## Комитет (Phase 2)

`/council TICKER` (владелец): 4 специалиста параллельно (новости / техника /
дивиденды / настроения Smart-Lab) → adversarial дебаты Bull vs Bear (до 3 раундов,
ранний выход при сходимости) → Portfolio Manager (вердикт + тезис + триггер
инвалидации) → Risk Manager с правом вето (жёсткие лимиты кодом: концентрация >15%,
переуверенность на тонких данных). Оркестрация — LangGraph. Вердикты пишутся в
`calls` (source='council') и попадают в /track с первого дня. Полный протокол
дебатов — кнопкой «📜 Протокол». Стоимость прогона ~$0.2-0.4.
```

- [ ] **Step 2: Deploy**

```bash
railway up --service app --ci
```

- [ ] **Step 3: MANUAL — E2E-чеклист (владелец)**

- [ ] `/council SBER` → прогресс меняется по стадиям (аналитики → дебаты → PM → Risk) → вердикт с голосами и тезисом за 60–120 сек
- [ ] Кнопка «📜 Протокол» (владелец) → полный протокол (мнения 4 ролей + ходы дебатов)
- [ ] `/track` → счётчик «Без единой оценки» вырос на 1 (одобренный вердикт попал в calls; проверка: `SELECT count(*) FROM calls WHERE source='council'` через psql на Railway)
- [ ] Вето Risk (если случится): вердикт показан с ⛔️, счётчик «Без единой оценки» НЕ вырос (вето не пишется в track-record)
- [ ] Гость: `/council SBER` → вежливый отказ с подсказкой /ask; тап по чужой кнопке «📜 Протокол» → alert «только владельцу»
- [ ] `/council XXXX` → «не знаю бумагу»
- [ ] В `usage_log`: операции council_news/technical/fundamentals/sentiment/debate_*/manager/risk; суммарная стоимость прогона <$0.50
- [ ] Пустой счёт: вердикт в «режиме идей», Risk не вето-ит по концентрации

- [ ] **Step 4: Тег**

```bash
git add README.md && git commit -m "docs: phase 2 committee README" && git tag phase-2
```

---

## Adversarial review (2026-07-12, мультиагентный: 3 ревьюера × верификация)

20 сырых находок → 13 подтверждено → 10 уникальных дефектов исправлено в этой версии:
owner-гейт на кнопку протокола (blocker: утечка позиции гостям); вето-вердикты не пишутся
в calls (blocker: скорились бы как реальные ставки); фикстура council_ctx в conftest вместо
кросс-импорта тест-модулей (major); epoch-1970 у Tinkoff Dividend.payment_date → фильтр по
году (major); будущие дивиденды исключены из 12-мес суммы, показываются как «Объявлено»
(major); тест sell-кейса без ложного overconfidence-вето (blocker в тесте); volume_ratio
2.3 сразу в теле теста (minor); стадии прогресса анонсируют СЛЕДУЮЩИЙ шаг (minor);
chunk_lines рубит сверхдлинные строки (minor); E2E-чеклист проверяемый + вето-кейс (minor).

## Self-review checklist (выполнен при написании)

- **Spec §7 coverage:** 4 специалиста structured output ✅ (T7) · adversarial framing Bull/Bear ✅ (T8) · дебаты ≤3 раундов, early-exit ✅ (T8, T10) · PM proposal+тезис+инвалидация ✅ (T9) · Risk hard limits + вето ✅ (T9) · cost-routing gpt-4o/o4-mini ✅ (T7-9) · вердикт в calls → track-record ✅ (T13) · LangGraph ✅ (T10)
- **Пустой счёт:** weight=None → нет вето по концентрации (T9 тест) · PM «режим идей» в промпте (T9) · контекст переживает пустой портфель (T6 тест) ✅
- **Типы согласованы:** `CouncilContext` (T6) потребляется T7-T9, T13; `debate_log: list[dict]` с ключами speaker/argument/position_after единообразен T8/T9/T10/T12; `Indicators.as_text(last_close)` (T2) вызывается в T7; `save_call(source="council")` соответствует сигнатуре из Phase 1.5 ✅
- **Placeholder scan:** каждый шаг с полным кодом; manual — чеклисты ✅
- **Приватность:** /council owner-only; position_note только для владельца (уже в context) ✅
