# Phase 5.6 «Инцидент Tinkoff TLS + пульс» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Оживить бота после месячной слепоты (Tinkoff API отвергается контейнером из-за сертификата Минцифры), сделать так, чтобы деградация никогда больше не была бесшумной (пульс для владельца, честные пометки о возрасте данных), и вычистить шум, который стал виден в сентябрьских дайджестах.

**Architecture:** (1) Российские корневые сертификаты вендорятся в репо и ставятся в системное хранилище образа; gRPC и httpx направляются на системный бандл через env. (2) `health.py` — модульный трекер успех/сбой по зависимости «tinkoff» (все публичные методы TinkoffBroker обёрнуты декоратором); часовая джоба шлёт владельцу «🩺 недоступен с …» раз в день и «✅ снова отвечает» при восстановлении. (3) Кэш портфеля хранит wall-clock время снимка; дайджест: >1ч — баннер о возрасте данных, >24ч — честное короткое сообщение вместо дайджеста (без LLM-коста). (4) `news/filters.py`: спорт/лига ВТБ и «старые по адресу» статьи РБК не считаются новостями компании. (5) `fmt_price` во всех строках сделок.

**Tech Stack:** существующий, новых зависимостей НЕТ. Сертификаты — публичные файлы Минцифры (gu-st.ru), в репо как `certs/*.crt`.

**Verification model:** тесты в CI; деплой `railway up --service app --ci`; ГЕЙТ инцидента — после деплоя в логах `universe_loaded count=46` (list_shares идёт через Tinkoff gRPC: если он прошёл — TLS починен) и отсутствие `Handshake failed`.

**Зафиксированные решения:**
1. Сертификаты — в репо (`certs/`), а не скачиваются при билде: билдер Railway вне РФ, gu-st.ru может быть недоступен; файлы публичные, ~2 КБ.
2. gRPC: `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt` (системный бандл после update-ca-certificates содержит и Mozilla-корни, и российские). httpx: `SSL_CERT_FILE` на тот же бандл — на будущее, если MOEX/РБК/Интерфакс переедут на российский УЦ.
3. Пульс — отдельная джоба каждый час в :50; алерт владельцу через send_alert (ночью — в буфер); дедуп раз в день; порог «недоступен» — 1 час без единого успешного вызова при наличии сбоев.
4. Возраст снимка: ≤1ч — молчим; 1–24ч — баннер в дайджесте; >24ч — дайджест НЕ строим (и LLM не зовём), шлём короткое честное сообщение. Порог одинаков для всех юзеров.
5. Шум новостей: url содержит `/sport/` или host `sport-interfax.ru` → выкидываем до матчинга; заголовок содержит «лиги ВТБ»/«лига ВТБ»/«ВТБ Арена» → выкидываем; РБК-адрес вида `/dd/mm/yyyy/` старше 3 дней относительно published_at → выкидываем (РБК бампит pubDate у старых материалов).
6. `fmt_price` — публичное имя в formatting.py; применяется в digest-секции сделок, /deals, сигналах уровней, сообщениях сверки (вход/цена).

---

### Task 1: Сертификаты + Dockerfile

**Files:**
- Create: `certs/russian_trusted_root_ca_pem.crt`, `certs/russian_trusted_sub_ca_pem.crt` (уже скопированы из scratchpad, PEM проверен)
- Modify: `Dockerfile`

- [ ] **Step 1: Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# git нужен для установки Tinkoff SDK (он git-only, удалён с PyPI)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tinkoff Invest API подписан УЦ Минцифры — без этих корней gRPC видит
# «self signed certificate in certificate chain» и бот слепнет (инцидент 09.2026)
COPY certs/*.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir --no-deps \
       "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta117"

COPY scripts ./scripts
COPY db ./db

CMD ["python", "-m", "roaring_kittens.main"]
```

- [ ] **Step 2: Commit**

```bash
git add certs Dockerfile
git commit -m "fix: trust Russian CA roots for Tinkoff gRPC (TLS outage since Sept)"
```

---

### Task 2: health.py + декоратор на TinkoffBroker

**Files:**
- Create: `src/roaring_kittens/health.py`
- Modify: `src/roaring_kittens/broker/tinkoff_client.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_health.py
from datetime import datetime, timedelta, timezone

from roaring_kittens.health import DependencyHealth

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def test_down_only_after_threshold_without_success():
    h = DependencyHealth(threshold=timedelta(hours=1))
    assert h.is_down(now=T0) is False                  # ничего не знаем — не паникуем
    h.note_failure("tls", now=T0)
    assert h.is_down(now=T0 + timedelta(minutes=30)) is False  # порог не вышел
    h.note_failure("tls", now=T0 + timedelta(minutes=61))
    assert h.is_down(now=T0 + timedelta(minutes=61)) is True   # час сбоев без успеха
    assert h.last_error == "tls"


def test_success_resets_down_and_tracks_down_since():
    h = DependencyHealth(threshold=timedelta(hours=1))
    h.note_success(now=T0)
    h.note_failure("x", now=T0 + timedelta(minutes=10))
    h.note_failure("x", now=T0 + timedelta(hours=2))
    assert h.is_down(now=T0 + timedelta(hours=2)) is True
    assert h.down_since == T0 + timedelta(minutes=10)     # первый сбой после успеха
    h.note_success(now=T0 + timedelta(hours=3))
    assert h.is_down(now=T0 + timedelta(hours=3)) is False
    assert h.down_since is None
```

- [ ] **Step 2: Реализовать health.py**

```python
# src/roaring_kittens/health.py
"""Пульс внешних зависимостей: бесшумная деградация запрещена (инцидент 09.2026 —
Tinkoff TLS падал месяц, а бот показывал застывший портфель)."""
import functools
from datetime import datetime, timedelta, timezone


class DependencyHealth:
    def __init__(self, threshold: timedelta = timedelta(hours=1)):
        self.threshold = threshold
        self.last_ok: datetime | None = None
        self.down_since: datetime | None = None   # первый сбой после последнего успеха
        self.last_error: str | None = None
        self.alerted_on: str | None = None        # 'YYYY-MM-DD' последнего 🩺-алерта
        self.recovery_pending = False             # алерт был -> при успехе шлём ✅

    def note_success(self, now: datetime | None = None) -> None:
        self.last_ok = now or datetime.now(tz=timezone.utc)
        self.down_since = None
        self.last_error = None

    def note_failure(self, error: str, now: datetime | None = None) -> None:
        now = now or datetime.now(tz=timezone.utc)
        if self.down_since is None:
            self.down_since = now
        self.last_error = error[:300]

    def is_down(self, now: datetime | None = None) -> bool:
        if self.down_since is None:
            return False
        now = now or datetime.now(tz=timezone.utc)
        return now - self.down_since >= self.threshold


tinkoff = DependencyHealth()


def track(dep: DependencyHealth):
    """Декоратор: успех/сбой async-вызова -> пульс зависимости."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                dep.note_failure(str(exc))
                raise
            dep.note_success()
            return result
        return wrapper
    return deco
```

- [ ] **Step 3: tinkoff_client.py — обернуть все 5 публичных методов**

Импорт: `from roaring_kittens import health`. На каждый метод (`get_portfolio`,
`get_daily_candles`, `get_dividends`, `get_last_prices`, `list_shares`) —
декоратор `@health.track(health.tinkoff)` ВЫШЕ `@retry_async(...)` (считаем итог
после ретраев, а не каждую попытку):

```python
    @health.track(health.tinkoff)
    @retry_async(attempts=3, base_delay=1.0)
    async def get_portfolio(self) -> PortfolioSnapshot:
```

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/health.py src/roaring_kittens/broker/tinkoff_client.py tests/test_health.py
git commit -m "feat: dependency health tracking on every Tinkoff call"
```

---

### Task 3: Пульс-джоба для владельца

**Files:**
- Modify: `src/roaring_kittens/scheduler.py`

- [ ] **Step 1: health_job**

```python
async def health_job(deps: Deps, bot) -> None:
    """Каждый час: Tinkoff лежит >1ч -> владельцу 🩺 раз в день; ожил -> ✅ один раз."""
    from roaring_kittens import health
    from roaring_kittens.db.owner import fetch_owner_id
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    h = health.tinkoff
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    if h.is_down():
        if h.alerted_on == today:
            return
        since = h.down_since.astimezone(_msk()).strftime("%d.%m %H:%M")
        text = (f"🩺 <b>Tinkoff API недоступен с {since} МСК.</b>\n"
                f"Не работают: портфель и дайджест, сигналы по сделкам, сканер, "
                f"скоринг. Новости и алерты по ним — работают.\n"
                f"Ошибка: <code>{esc((h.last_error or '')[:160])}</code>")
        await send_alert(deps, bot, owner_id, text)
        h.alerted_on = today          # ТОЛЬКО после успешной отправки
        h.recovery_pending = True
    elif h.recovery_pending and h.last_ok is not None:
        await send_alert(deps, bot, owner_id,
                         "✅ Tinkoff API снова отвечает — портфель, сигналы и сканер "
                         "работают в штатном режиме.")
        h.recovery_pending = False
```

`_msk()` — `from zoneinfo import ZoneInfo; return ZoneInfo(deps.settings.tz)`
(tz уже есть в Settings и используется шедулером). В `build_scheduler`:

```python
    scheduler.add_job(health_job, "cron", minute=50, args=[deps, bot],
                      id="health", max_instances=1, coalesce=True)
```

- [ ] **Step 2: Commit**

```bash
git add src/roaring_kittens/scheduler.py
git commit -m "feat: hourly health pulse — owner alert when Tinkoff is down, recovery notice"
```

---

### Task 4: Возраст снимка портфеля + честный дайджест

**Files:**
- Modify: `src/roaring_kittens/users_service.py`, `src/roaring_kittens/digest/morning.py`, `tests/test_users_service.py`
- Test: `tests/test_digest_staleness.py`

- [ ] **Step 1: users_service — wall-clock время снимка**

Кэш: `deps.portfolio_cache[uid] = (monotonic, snap, fetched_at_utc)`. В
`get_cached_portfolio` при успехе писать тройку; при фолбэке возвращать `cached[1]`
как раньше. Новый хелпер:

```python
def cached_portfolio_age(deps, telegram_id: int) -> timedelta | None:
    """Сколько снимку лет; None — снимка нет."""
    cached = deps.portfolio_cache.get(telegram_id)
    if not cached:
        return None
    return datetime.now(tz=timezone.utc) - cached[2]
```

Существующий тест TTL (`deps.portfolio_cache[111] = (time.monotonic() - 9999, snap1)`)
→ тройка `(time.monotonic() - 9999, snap1, datetime.now(tz=timezone.utc))`.

- [ ] **Step 2: Падающий тест чистой функции**

```python
# tests/test_digest_staleness.py
from datetime import datetime, timedelta, timezone

from roaring_kittens.digest.morning import staleness_verdict

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


def test_fresh_snapshot_is_silent():
    assert staleness_verdict(timedelta(minutes=20), now=NOW) == ("ok", None)


def test_hours_old_snapshot_gets_banner():
    kind, text = staleness_verdict(timedelta(hours=5), now=NOW)
    assert kind == "banner" and "⚠️" in text and "28.09" in text


def test_day_old_snapshot_aborts_digest():
    kind, text = staleness_verdict(timedelta(days=3), now=NOW)
    assert kind == "abort" and "3 дн" in text
```

- [ ] **Step 3: morning.py**

```python
STALE_BANNER_AFTER = timedelta(hours=1)
STALE_ABORT_AFTER = timedelta(hours=24)


def staleness_verdict(age: timedelta | None,
                      now: datetime | None = None) -> tuple[str, str | None]:
    """('ok'|'banner'|'abort', текст). Дайджест не должен выдавать старый
    снимок счёта за сегодняшний (инцидент 09.2026 — месяц застывших цифр)."""
    if age is None or age < STALE_BANNER_AFTER:
        return "ok", None
    now = now or datetime.now(tz=timezone.utc)
    taken = (now - age).astimezone(timezone(timedelta(hours=3)))  # МСК
    if age >= STALE_ABORT_AFTER:
        days = age.days
        return "abort", (f"⚠️ Не вижу твой счёт уже {days} дн — Tinkoff API не "
                         f"отвечает (последние данные {taken:%d.%m %H:%M} МСК). "
                         f"Дайджест приостановлен, пришлю обычный, как только "
                         f"связь вернётся.")
    return "banner", (f"⚠️ Данные счёта от {taken:%d.%m %H:%M} МСК — Tinkoff "
                      f"временно недоступен, цифры ниже могли устареть.")
```

В `run_morning_digest` после получения `snap` через кэш:

```python
    from roaring_kittens.users_service import cached_portfolio_age
    kind, note = staleness_verdict(cached_portfolio_age(deps, chat_id))
    if kind == "abort":
        await bot.send_message(chat_id, note)
        log.warning("digest_aborted_stale_portfolio", chat=chat_id)
        return
```

и в `build_digest_text(...)` первой строкой после «☀️ Доброе утро!» — `note`, если
`kind == "banner"` (передать параметром `banner: str | None = None`).

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/users_service.py src/roaring_kittens/digest/morning.py tests/test_users_service.py tests/test_digest_staleness.py
git commit -m "feat: digest is honest about stale portfolio snapshots"
```

---

### Task 5: news/filters.py — спорт и старые статьи

**Files:**
- Create: `src/roaring_kittens/news/filters.py`
- Modify: `src/roaring_kittens/scheduler.py` (poll_news)
- Test: `tests/test_news_filters.py`

- [ ] **Step 1: Падающий тест**

```python
# tests/test_news_filters.py
from datetime import datetime, timedelta, timezone

from roaring_kittens.news.filters import is_noise
from roaring_kittens.news.models import NewsItem

NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)


def _n(url, headline, published=NOW, source="rbc"):
    return NewsItem(source=source, url=url, headline=headline, body=None,
                    published_at=published, tickers=[])


def test_sport_sections_and_vtb_league_are_noise():
    assert is_noise(_n("https://www.rbc.ru/sport/17/08/2026/x", "Турнир перенесли"), NOW)
    assert is_noise(_n("https://www.sport-interfax.ru/1117286", "Суперкубок",
                       source="interfax"), NOW)
    assert is_noise(_n("https://www.rbc.ru/business/04/09/2026/x",
                       "Иностранный клуб выиграл Суперкубок Единой лиги ВТБ"), NOW)
    assert is_noise(_n("https://www.rbc.ru/business/04/09/2026/x",
                       "Концерт на ВТБ Арене"), NOW)


def test_rbc_url_date_older_than_3_days_is_stale_noise():
    # РБК бампит pubDate у старых материалов — верим дате в адресе
    assert is_noise(_n("https://www.rbc.ru/economics/20/08/2026/x", "Кадры"), NOW)
    assert not is_noise(_n("https://www.rbc.ru/economics/03/09/2026/x", "Свежее"), NOW)
    assert not is_noise(_n("https://www.interfax.ru/business/1112894", "Греф"), NOW,)
```

- [ ] **Step 2: Реализовать**

```python
# src/roaring_kittens/news/filters.py
"""Что НЕ считается новостью компании: спорт под брендом банка и «старые по
адресу» статьи РБК (сентябрь 2026: «лига ВТБ» и Халк Хоган в дайджесте)."""
import re
from datetime import datetime, timedelta

from roaring_kittens.news.models import NewsItem

SPORT_URL_MARKERS = ("/sport/", "sport-interfax.ru", "sport.interfax")
SPORT_HEADLINE_RE = re.compile(r"лиг[аи] ВТБ|ВТБ[\s-]?Арен", re.IGNORECASE)
RBC_URL_DATE_RE = re.compile(r"/(\d{2})/(\d{2})/(\d{4})/")
STALE_URL_DAYS = 3


def is_noise(item: NewsItem, now: datetime) -> bool:
    url = item.url.lower()
    if any(m in url for m in SPORT_URL_MARKERS):
        return True
    if SPORT_HEADLINE_RE.search(item.headline):
        return True
    m = RBC_URL_DATE_RE.search(item.url)
    if m:
        day, month, year = (int(x) for x in m.groups())
        try:
            url_date = datetime(year, month, day, tzinfo=now.tzinfo)
        except ValueError:
            return False
        if now - url_date > timedelta(days=STALE_URL_DAYS):
            return True
    return False
```

- [ ] **Step 3: poll_news — фильтр до матчинга**

```python
        items = await fetch_feed(url, source=source_id)
        now = datetime.now(tz=timezone.utc)
        items = [i for i in items if not is_noise(i, now)]
```

(импорт `from roaring_kittens.news.filters import is_noise`).

- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens/news/filters.py src/roaring_kittens/scheduler.py tests/test_news_filters.py
git commit -m "feat: drop sport sections, VTB-league and stale-by-url RBC items before matching"
```

---

### Task 6: fmt_price во всех строках сделок

**Files:**
- Modify: `telegram/formatting.py` (публичный `fmt_price = _fmt_price`), `digest/morning.py`, `telegram/handlers/deals.py`, `deals_service.py`, `price_watch.py`

- [ ] **Step 1:** в formatting.py после `_fmt_price` добавить `fmt_price = _fmt_price`.
- [ ] **Step 2:** заменить в f-строках: `{entry}` → `{fmt_price(entry)}`, `{now_p}` /
`{now_price}` / `{price}` → `fmt_price(...)`, `{d.target_price}` / `{d.exit_price}` /
`{target}` / `{exit_price}` → `fmt_price(...)`, `{pos.avg_price}` → `fmt_price(pos.avg_price)`,
`{d.entry_suggested}` → `fmt_price(d.entry_suggested)` — в: morning.py (секция «Твои
сделки»), deals.py (format_deals, cb_take/cb_sold ответы, карточки «Ждёт решения»),
deals_service.py (build_idea_text: entry/target/exit; sync-сообщения), price_watch.py
(watch_deal_levels: price/exit/target). qty (`pos.quantity`) → `_fmt_qty`
(экспортировать как `fmt_qty`).
- [ ] **Step 3:** test_deal_render — добавить `assert "293.38000000" not in text` для
`entry=Decimal("293.38000000")`.
- [ ] **Step 4: Commit**

```bash
git add src/roaring_kittens tests/test_deal_render.py
git commit -m "fix: no Decimal tails in deal lines (fmt_price everywhere)"
```

---

### Task 7: README/STATUS, деплой, гейт

- [ ] README: абзац «Надёжность» — сертификаты Минцифры в образе, пульс 🩺, честный дайджест.
- [ ] Deploy `railway up --service app --ci`. ГЕЙТ: в логах `universe_loaded count=46`
(gRPC через новый бандл прошёл) и НЕТ `Handshake failed`; через час — `health` не шлёт 🩺.
- [ ] MANUAL: завтра 8:50 сверка — «✅»/конвертация без ошибок; 9:00 дайджест с живыми
цифрами и без баннера; 10:40 `scanner_screened total≈10`.
- [ ] Тег `phase-5.6`.

---

## Self-review checklist

- Четыре пункта, согласованные с юзером: сертификаты ✅ (T1) · пульс ✅ (T2-T3) · честность данных ✅ (T4) · косметика+шум ✅ (T5-T6)
- Типы: `DependencyHealth` (T2) в T3; `cached_portfolio_age` (T4) в morning.py; `staleness_verdict` чистая; `is_noise(item, now)` в poll_news; `fmt_price/fmt_qty` (T6)
- Инварианты: `alerted_on` ставится ТОЛЬКО после успешной отправки; abort-дайджест не зовёт LLM; фильтр шума — до матчинга (сохранение в БД тоже не нужно); health.track снаружи retry — считает итог
