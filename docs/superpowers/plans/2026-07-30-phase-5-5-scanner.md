# Phase 5.5 «Сканер голубых фишек + язык для людей» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ежедневный проактивный поток идей сделок по голубым фишкам через дешёвую воронку (скрининг mini → комитет только по лучшему кандидату), плюс вычистить слово «тезис» из юзерских текстов и переписать /help вокруг сделок.

**Architecture:** Universe начинает хранить веса IMOEX (они уже есть в ISS-ответе) → `top_by_weight(10)`. Новый `scanner.py`: пн-пт 10:40 МСК — кандидаты (топ-10 минус свежесканированные), по каждому код-сигналы (RSI/MA из свечей, счёт новостей за 24ч из БД) + ОДИН gpt-4o-mini вызов на бумагу (score 0-100) → комитет ТОЛЬКО по лучшему с score ≥ 70 (≤1 комитет/день, guard council_ran_recently 24ч) → approved BUY → `propose_deal_from_council` каждому активному юзеру с брокером (все per-user guards уже внутри). Кост системный (вне use_user): скрининг ~$0.01/день, комитет ≤$0.4/день только при кандидате.

**Tech Stack:** существующий, новых зависимостей НЕТ.

**Verification model:** тесты в GitHub Actions CI; батчи → push → `gh run watch`; деплой `railway up --service app --ci`.

**Зафиксированные решения:**
1. Пул — топ-10 IMOEX по весу индекса (динамический, из ISS при загрузке universe; фолбэк на SEED — вес 0, сканер молчит до успешной загрузки ISS).
2. Расписание — пн-пт 10:40 МСК (после открытия и утренней сверки; вечерние сессии не сканируем).
3. Воронка: скрининг всех кандидатов → комитет максимум по ОДНОМУ в день (лучший score, порог ≥70). Кандидаты исключаются, если council_ran_recently(24ч) — не дублируем импакт/ручные комитеты.
4. Рассылка идей — всем active-юзерам с брокером; все существующие guards (нет позиции, 7 дней/тикер, live deal, TTL 48ч) работают как есть; source сделки = 'scanner'.
5. Кост — системный (user_id=NULL в usage_log): сканер — общая инфраструктура, как классификатор новостей.
6. Терминология (только юзер-тексты, код не трогаем): «🎯 Тезис:» → «🎯 Идея:», «Тезис по X СЛОМАН/ослаблен» → «🚨 Идея по X сломана» / «⚠️ Идея по X под вопросом», «Сгенерировал тезис» → «Моя идея по бумаге», «📌 Активные тезисы» → «📌 Почему держим», «Принять тезис» (кнопки) → «Принять идею», «Новый тезис» аналогично. Команда /thesis остаётся (алиасы не плодим).
7. /help — переписан вокруг сделок (структура: «💼 Сделки — главное» → «💡 Спросить» → «для всех/подключённых/admin»).

---

## Файловая структура (дельта)

```
src/roaring_kittens/
├── scanner.py              # NEW: воронка скрининг → комитет → идеи
├── universe/universe.py    # MOD: веса IMOEX, top_by_weight
├── scheduler.py            # MOD: scanner_job cron mon-fri 10:40
├── committee/render.py     # MOD: «Идея» вместо «Тезис»
├── telegram/handlers/
│   ├── thesis.py           # MOD: тексты «Почему держим»
│   ├── council.py          # MOD: кнопка «Принять идею»
│   └── start.py            # MOD: HELP_TEXT переписан
├── positions_sync.py       # MOD: «Моя идея по бумаге»
└── (scheduler.py validator-тексты «Идея … сломана»)
tests/: test_scanner.py (+MOD test_universe)
```

---

### Task 1: Universe — веса IMOEX + top_by_weight

**Files:**
- Modify: `src/roaring_kittens/universe/universe.py`, `tests/test_universe.py`

- [ ] **Step 1: Падающий тест (дописать в test_universe.py)**

```python
async def test_top_by_weight_orders_and_filters():
    def iss_handler(request):
        return httpx.Response(200, json=ISS_SAMPLE)  # SBER 14.2, GAZP 9.1

    class FakeBroker:
        async def list_shares(self):
            return {"SBER": ("BBG004730N88", "Сбер Банк", 10),
                    "GAZP": ("BBG004730RP0", "Газпром", 10)}

    uni = Universe(broker=FakeBroker(), transport=httpx.MockTransport(iss_handler))
    await uni.load()
    top = uni.top_by_weight(5)
    assert [i.ticker for i in top] == ["SBER", "GAZP"]  # по убыванию веса
    assert uni.top_by_weight(1)[0].ticker == "SBER"
```

- [ ] **Step 2: Реализовать**

```python
def parse_iss_weights(payload: dict) -> dict[str, float]:
    block = payload["analytics"]
    ti = block["columns"].index("ticker")
    wi = block["columns"].index("weight")
    return {row[ti]: float(row[wi] or 0) for row in block["data"]}
```

В `Universe.__init__`: `self._weights: dict[str, float] = {}`.
В `_fetch_index_tickers` сейчас возвращаются только тикеры — переработать:
`load()` вызывает `payload`-хелпер один раз; при успехе ISS сохранять
`self._weights = parse_iss_weights(payload)`, при фолбэке на SEED — веса пустые
(сканер честно молчит). Проще всего: `_fetch_index_tickers` → `_fetch_index`
возвращает `(tickers, weights)`; при исключении — `(list(SEED_TICKERS), {})`.

```python
    def top_by_weight(self, n: int) -> list[Instrument]:
        """Топ-N загруженных инструментов по весу IMOEX (голубые фишки)."""
        ranked = sorted((t for t in self._by_ticker if t in self._weights),
                        key=lambda t: self._weights[t], reverse=True)
        return [self._by_ticker[t] for t in ranked[:n]]
```

- [ ] **Step 3: Commit**

```bash
git add src/roaring_kittens/universe/universe.py tests/test_universe.py
git commit -m "feat: IMOEX weights in universe with top_by_weight"
```

---

### Task 2: scanner.py — воронка

**Files:**
- Create: `src/roaring_kittens/scanner.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: Падающий тест (pure-отбор кандидата)**

```python
# tests/test_scanner.py
from roaring_kittens.scanner import ScreenVerdict, pick_best


def _v(ticker, score, attractive=True):
    return ticker, ScreenVerdict(attractive=attractive, score=score,
                                 reason_short="r")


def test_pick_best_takes_highest_above_threshold():
    best = pick_best([_v("SBER", 55), _v("LKOH", 82), _v("GAZP", 74)])
    assert best[0] == "LKOH"


def test_pick_best_none_when_below_threshold_or_unattractive():
    assert pick_best([_v("SBER", 69), _v("GAZP", 50)]) is None
    assert pick_best([_v("SBER", 90, attractive=False)]) is None
    assert pick_best([]) is None
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/scanner.py
"""Сканер голубых фишек: дешёвый скрининг (mini) -> комитет по лучшему -> идеи.

Кост системный (вне use_user): скрининг ~$0.001/бумага, комитет <=1/день."""
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.broker.tech import compute_indicators
from roaring_kittens.db.calls import council_ran_recently
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.users import list_active_users
from roaring_kittens.deals_service import propose_deal_from_council
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.news.sources import CROWD_SOURCES
from roaring_kittens.users_service import get_user_broker

log = structlog.get_logger()

SCAN_TOP_N = 10
SCORE_THRESHOLD = 70
SCREEN_MODEL = "gpt-4o-mini"

SCREEN_SYSTEM = """Ты — скринер акций Мосбиржи. По технике и свежим заголовкам оцени,
интересна ли бумага К ПОКУПКЕ ПРЯМО СЕЙЧАС для консервативного частного инвестора.
score 0-100 (70+ = стоит полного разбора комитетом). Не выдумывай фактов.
Обзорные/пустые дни — низкий score. По-русски, кратко."""


class ScreenVerdict(BaseModel):
    attractive: bool
    score: int = Field(ge=0, le=100)
    reason_short: str = Field(description="одна фраза почему")


def pick_best(scored: list[tuple[str, ScreenVerdict]]):
    """(ticker, verdict) с максимальным score >= порога, только attractive."""
    good = [(t, v) for t, v in scored if v.attractive and v.score >= SCORE_THRESHOLD]
    if not good:
        return None
    return max(good, key=lambda x: x[1].score)


async def _screen_one(deps, instrument) -> ScreenVerdict | None:
    try:
        candles = await deps.broker.get_daily_candles(instrument.figi, days=60)
        ind = compute_indicators(candles)
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [instrument.ticker],
                                              since=since)
        news = [n for n in news if n.source not in CROWD_SOURCES]
        headlines = "\n".join(f"- {n.headline}" for n in news[:5]) or "(нет свежих)"
        user = (f"Тикер: {instrument.ticker} ({instrument.name})\n"
                f"Техника: RSI14={ind.rsi14}, MA20={ind.ma20}, MA50={ind.ma50}, "
                f"объём/среднему={ind.volume_ratio}\n"
                f"Заголовки за 24ч:\n{headlines}")
        return await deps.llm.parse(
            model=SCREEN_MODEL, operation="scanner_screen",
            messages=[{"role": "system", "content": SCREEN_SYSTEM},
                      {"role": "user", "content": user}],
            schema=ScreenVerdict)
    except Exception as exc:
        log.warning("scanner_screen_failed", ticker=instrument.ticker,
                    error=str(exc))
        return None


async def scanner_job(deps, bot) -> None:
    """Пн-пт 10:40: скрининг топ-10 IMOEX -> комитет по лучшему -> идеи юзерам."""
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    candidates = []
    for instrument in deps.universe.top_by_weight(SCAN_TOP_N):
        async with deps.session_factory() as session:
            if await council_ran_recently(session, instrument.ticker, hours=24):
                continue  # импакт/ручной комитет уже был — не дублируем
        candidates.append(instrument)
    if not candidates:
        log.info("scanner_no_candidates")
        return
    scored = []
    for instrument in candidates:
        verdict = await _screen_one(deps, instrument)
        if verdict is not None:
            scored.append((instrument.ticker, verdict))
    best = pick_best(scored)
    log.info("scanner_screened", total=len(scored),
             best=best[0] if best else None,
             best_score=best[1].score if best else None)
    if best is None:
        return
    instrument = deps.universe.get(best[0])
    try:  # комитет без позиционного контекста (broker=None): рыночный скан
        from roaring_kittens.committee.runner import run_council_flow
        outcome = await run_council_flow(deps, instrument, owner_id, broker=None)
    except Exception as exc:
        log.error("scanner_council_failed", ticker=best[0], error=str(exc))
        return
    if not outcome.risk.approved or outcome.proposal.action != "buy":
        log.info("scanner_council_no_buy", ticker=best[0],
                 action=outcome.proposal.action)
        return
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    for u in users:  # идея каждому подключённому; per-user guards внутри propose
        try:
            broker = await get_user_broker(deps, u.telegram_id)
            if broker is None:
                continue
            await propose_deal_from_council(deps, bot, u.telegram_id,
                                            instrument, outcome)
        except Exception as exc:
            log.error("scanner_propose_failed", user=u.telegram_id,
                      error=str(exc))
```

- [ ] **Step 3: scheduler.py — джоба**

```python
from roaring_kittens.scanner import scanner_job
...
    scheduler.add_job(scanner_job, "cron", day_of_week="mon-fri",
                      hour=10, minute=40, args=[deps, bot],
                      id="scanner", max_instances=1, coalesce=True)
```

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/scanner.py src/roaring_kittens/scheduler.py tests/test_scanner.py
git commit -m "feat: daily blue-chip scanner funnel (mini screening -> single committee)"
```

---

### Task 3: Терминология «тезис» → «идея» в юзер-текстах

**Files:**
- Modify: `committee/render.py`, `telegram/handlers/thesis.py`, `telegram/handlers/council.py`, `positions_sync.py`, `scheduler.py`

- [ ] **Step 1: Замены (только строки сообщений, имена функций/полей НЕ трогаем):**

- render.py: `f"🎯 Тезис: {esc(proposal.thesis)}"` → `f"🎯 Идея: {esc(proposal.thesis)}"`
- thesis.py format_theses: заголовок `"📌 <b>Активные тезисы:</b>"` → `"📌 <b>Почему держим:</b>"`; пустое состояние «Активных тезисов нет…» → «Пока нет бумаг под сопровождением. Идея появляется из /council (кнопка «Принять идею») или автоматически для позиций ≥5% портфеля.»; hint «Каждая свежая новость по тикеру проверяет тезис автоматически.» → «…проверяет идею автоматически.»
- thesis.py cb_thesis_save ответ: «📌 Тезис по X принят» → «📌 Идея по X принята»; «Этот тезис уже принят» → «Эта идея уже принята»
- council.py + scheduler.py кнопки: «📌 Принять тезис» → «📌 Принять идею», «📌 Принять новый тезис» → «📌 Принять новую идею»
- positions_sync.py: «Сгенерировал тезис: …» → «Моя идея по бумаге: …»; «…без тезиса» → «…без сопровождения»; «🗑 Удалить тезис» (кнопка) → «🗑 Не согласен — убрать»
- scheduler.py validator: `f"⚠️ Тезис по <b>{ticker}</b> {'СЛОМАН' if ... else 'ослаблен'}: ..."` → СЛОМАН-ветка: `f"🚨 Идея по <b>{ticker}</b> сломана: ..."`, weakened: `f"⚠️ Идея по <b>{ticker}</b> под вопросом: ..."`; строка `\nТезис: {esc(...)}` → `\nИдея была: {esc(...)}`; «🚨 Новости ломают тезис по X … Собираю комитет…» → «🚨 Новости ломают идею по X … Собираю комитет…»
- Проверка: `grep -rn "Тезис\|тезис" src/` — в СТРОКАХ сообщений юзеру слова не осталось (докстринги/комменты/имена — можно).

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens
git commit -m "feat: retail wording — thesis becomes idea in all user-facing texts"
```

---

### Task 4: HELP_TEXT — вокруг сделок

**Files:**
- Modify: `src/roaring_kittens/telegram/handlers/start.py`

- [ ] **Step 1: Заменить HELP_TEXT целиком**

```python
HELP_TEXT = (
    "🐱📈 <b>Roaring Kittens</b> — AI-помощник инвестора на Мосбирже.\n\n"
    "<b>💼 Сделки — главное:</b>\n"
    "Я сам слежу за новостями и рынком. Когда мой комитет аналитиков находит\n"
    "интересную покупку — присылаю идею: цена входа, 🎯 цель, 🛑 «продаём если»\n"
    "и размер под твой портфель. Жмёшь [Беру] → покупаешь в Т-Инвестициях →\n"
    "я вижу покупку на счёте и веду сделку до сигнала выхода.\n"
    "• <code>/deals</code> — идеи, открытые сделки с уровнями, закрытые с результатом\n"
    "• Свои покупки тоже подхвачу и буду вести.\n\n"
    "<b>💡 Спросить (доступно всем, гости — 10/день):</b>\n"
    "• Кнопка «💡 Спросить» или <code>/ask SBER почему падает?</code>\n"
    "• <code>/council ТИКЕР</code> — полный разбор комитетом (подключённым)\n"
    "• <code>/track</code> — мой послужной список vs индекс, включая промахи\n\n"
    "<b>Для подключённых:</b>\n"
    "• <code>/portfolio</code> — портфель и P&amp;L · <code>/digest</code> — сводка (сама в 9:00)\n"
    "• <code>/thesis</code> — почему держим каждую бумагу\n"
    "• <code>/watch ТИКЕР</code> — следить за бумагой без покупки (алерты + идеи)\n"
    "• <code>/budget</code> — AI-бюджет · <code>/token</code> — сменить токен\n\n"
    "<b>Подключиться:</b> нужен инвайт-код от владельца — просто пришли его сюда."
)
```

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/telegram/handlers/start.py
git commit -m "feat: help rewritten around the deals loop"
```

---

### Task 5: README, деплой, E2E

- [ ] **Step 1: README — абзац в раздел «Сделки»:** «Сканер: каждый торговый день в 10:40 скрининг топ-10 бумаг IMOEX (gpt-4o-mini, ~цент), полный комитет — только по лучшему кандидату (score≥70, ≤1/день). Идеи уходят всем подключённым.»
- [ ] **Step 2: Deploy** — `railway up --service app --ci`; логи: `bot_starting`; на следующий торговый день в 10:40 — `scanner_screened`.
- [ ] **Step 3: MANUAL E2E** — дождаться 10:40: лог scanner_screened (total≈10); если best прошёл порог — идея пришла; /help показывает новый текст; в сообщениях валидатора/комитета нет слова «тезис».
- [ ] **Step 4: Тег** — `git tag phase-5.5 && git push origin phase-5.5`

---

## Self-review checklist (выполнен при написании)

- Запросы юзера: «чаще, чем раз в неделю» ✅ (ежедневно пн-пт) · «топ бумаг / голубые фишки» ✅ (топ-10 по весу IMOEX) · «что такое тезис → слово непонятно» ✅ (T3) · «обновить помощь» ✅ (T4)
- Кост: скрининг ~10×$0.001/день + ≤1 комитет/день ($0.2-0.4) ≈ $5-9/мес, системный; guard council_ran_recently не даёт двойных комитетов ✅
- Типы: ScreenVerdict/pick_best (T2) самодостаточны; top_by_weight (T1) в T2; propose_deal_from_council/run_council_flow — существующие сигнатуры Phase 5 ✅
- Изоляция: идеи через propose_deal_from_council — все per-user guards Phase 5 работают; комитет сканера broker=None — без чьей-либо позиции в контексте; proto-кнопка в идею не входит ✅
