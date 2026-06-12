# Roaring Kittens — Design Spec

> **Статус:** Approved v1 · **Дата:** 2026-06-04 (обновлено 2026-06-12) · **Автор:** owner + Claude (brainstorming)
> **Название:** Roaring Kittens (финальное, утверждено owner)

---

## 1. Vision (одно предложение)

Telegram-native AI инвест-советник для частного инвестора на Московской бирже: **ансамбль из 8 LLM-агентов** проводит Bull/Bear дебаты по каждой позиции, учится на истории сделок конкретного пользователя и в реальном времени реагирует на high-impact новости — всё с обязательным подтверждением пользователя.

## 2. Цели и не-цели

### Цели
- Персональный «инвесткомитет» в Telegram, превосходящий примитивные сигнальные боты по качеству reasoning
- Обучаемость под конкретного пользователя (память сделок, тезисов, ошибок)
- Реактивность на внутридневные события, ломающие тезис (пример: ВТБ объявил дивиденды ниже консенсуса)
- Pet-проект на одного пользователя с возможностью пригласить друзей (friends & family testing, бесплатно)
- Portfolio piece для резюме AI Product Manager

### Не-цели (сознательно вне скоупа)
- Автоматическое исполнение ордеров (в f&f-режиме — только рекомендации + ручное исполнение пользователем)
- Day-trading / HFT (горизонт — swing + инвест, не intraday-скальпинг)
- Сканирование всего рынка через агентов (universe ограничен ~40 тикерами IMOEX)
- Публичный коммерческий сервис, биллинг, лицензия финкомпании
- Web/mobile UI, Telegram Mini App
- Social / copy-trading между пользователями
- Локальное хранилище знаний (Obsidian/Notion) — отклонено

## 3. Пользователи и сценарии

**Основной пользователь:** частный инвестор на Мосбирже со смешанным стилем (долгосрочный портфель + периодические swing-идеи), счёт в Т-Инвестициях, активно пользуется Telegram.

**Ключевые сценарии:**
1. Утренний дайджест в 9:00 МСК — состояние портфеля, ночные новости, идеи дня, статус тезисов
2. HIGH-impact алерт внутри дня — новость ломает тезис → комитет совещается → рекомендация с кнопками действий
3. Conversational запрос (`/ask стоит докупать Сбер?`) — полный прогон комитета по тикеру
4. Просмотр/редактирование тезиса позиции
5. Еженедельная ретроспектива (вс 23:00) — P&L, новые инсайты, разбор решений
6. Onboarding друга по invite-коду со своим портфелем

## 4. Рыночный контекст (research, май 2026)

- **Мировой тренд — мультиагентные системы:** TradingAgents (Tauric Research, ~60k★, arXiv 2412.20138), AI Hedge Fund (virattt, ~51k★), FinRobot (AI4Finance), академические FinMem/FinCon/FinAgent. Паттерн: ансамбль ролей → дебаты → risk-комитет.
- **Доказанный инсайт:** adversarial Bull/Bear дебаты дают +Sharpe против single-prompt (FinCon, arXiv 2407.06567).
- **Память:** layered memory (working/episodic/reflective) из FinMem (arXiv 2311.13743) — агент сохраняет и применяет уроки прошлых сделок.
- **Российский рынок:** Telegram-боты (Trsignal, Инвест Гусь, RussianInvestbot) — примитивные сигнальщики без reasoning. T-Bank AI Assistant сознательно не даёт рекомендаций (регуляторика ЦБ). **Дыра на рынке: русскоязычный мультиагентный дебат для MOEX не существует.**
- **Дифференциаторы:** (1) первый мультиагентный дебат для MOEX на русском; (2) персональная память + thesis tracker; (3) read-only + user-approval как фича, обходящая регуляторику.

## 5. Архитектура (high-level)

Монолитное async-приложение на Python, 4 логических слоя в одном процессе:

```
┌─────────────────────────────────────────────────────────────────┐
│  TELEGRAM LAYER (aiogram 3) — single bot, multi-user routing      │
│  • Handlers идентифицируют user по telegram_id                    │
│  • FSM для multi-step flows, admin-команды для role='admin'       │
└────────────┬──────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────────────┐
│  AGENT ORCHESTRATION (LangGraph + OpenAI)                          │
│  • Граф: Analysts → Bull/Bear Debate → PM → Risk → Output         │
│  • Memory manager (working/episodic/reflective)                    │
│  • Thesis tracker · Budget guard · Checkpoint resume               │
└────────────┬──────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────────────┐
│  GLOBAL DATA LAYER                                                 │
│  • News Watcher (RBC/e-disclosure/Smart-Lab/Tinkoff news)         │
│  • Market data via system Tinkoff token (свечи, инструменты)       │
│  • Universe IMOEX-40                                               │
└────────────┬──────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────────────┐
│  PER-USER STATE (PostgreSQL 16 + pgvector)                        │
│  • users (encrypted token, budget) · portfolios (cached)          │
│  • episodes / theses / insights (всё с user_id)                    │
│  • watchlists · usage_log · news_impacts                          │
└─────────────────────────────────────────────────────────────────────┘
```

**Принципы:** один процесс (проще дебажить/деплоить/хостить); async-first (нагрузка IO-bound); глобальный слой данных переиспользуется между юзерами для экономии cost; полная изоляция per-user состояния.

## 6. Технологический стек

| Слой | Технология | Обоснование |
|---|---|---|
| Язык | Python 3.12 | Лучший SDK Tinkoff, весь AI-тулинг |
| Telegram | aiogram 3 | Async, FSM, modern |
| Оркестрация | LangGraph 0.2+ | Граф агентов, checkpoint resume, провайдер-агностичен |
| LLM | OpenAI API (langchain-openai) | У пользователя есть ключ; mini-модели дешевле для классификации |
| Брокер | tinkoff-investments (official SDK) | gRPC, streams, портфель/свечи/новости |
| БД | PostgreSQL 16 + pgvector | State + векторная память (HNSW) |
| Эмбеддинги | text-embedding-3-small | Дёшево, достаточно для retrieval |
| Cron | APScheduler | Дайджест, скан, weekly reflection, news poll |
| Парсеры | feedparser + httpx + selectolax | RSS + HTML |
| Бэктест (V2) | vectorbt | Pandas-native, быстро |
| Деплой | Docker Compose | One-command |
| Хостинг | Railway (primary) / Timeweb (fallback) | Tinkoff API требует RU-IP; Railway US/EU — риск, есть fallback |
| Логи | structlog (JSON) | Фильтрация по user_id/run_id |
| Шифрование | cryptography.Fernet | Токены at rest |

**Распределение моделей (cost-routing):**

| Задача | Модель | ~Cost/op |
|---|---|---|
| Impact classification | gpt-4o-mini | ~$0.0005 |
| Аналитики (News/Tech/Fund/Sentiment) | gpt-4o / gpt-4.1 | ~$0.08 |
| Bull/Bear дебаты | o4-mini (дефолт) / o3 (по запросу юзера) | ~$0.10–0.30 |
| Portfolio Manager | gpt-4o / gpt-4.1 | ~$0.05 |
| Risk Manager | o4-mini | вкл. выше |
| Weekly reflection | o3 (раз в неделю — можно потратиться) | ~$0.30–0.50 |

> На ключе owner доступна вся линейка моделей OpenAI — routing ограничен только cost-соображениями, не доступностью.

## 7. Агенты: роли, дебаты, оркестрация

### Состав (8 агентов)

**Слой 1 — Аналитики (параллельно, structured output):**

| Агент | Зона | Источники | Output (ключевое) |
|---|---|---|---|
| News Analyst | События 24ч | Tinkoff news, RBC, Ведомости | sentiment, key_events[], risks[] |
| Fundamentals Analyst | Бизнес/финансы | E-disclosure, МСФО, дивполитика | valuation, dividend_thesis, red_flags[] |
| Technical Analyst | Цена/объём | Tinkoff candles, RSI/MACD/MA | trend, key_levels, signals[] |
| Sentiment Analyst | Настроения | Smart-Lab, инсайдерские сделки | sentiment, insider_activity, crowd_position |

**Слой 2 — Исследователи (adversarial debate):**
- **Bull Researcher** — строит сильнейший аргумент ЗА, даже при неоднозначных данных
- **Bear Researcher** — зеркально, сильнейший аргумент ПРОТИВ
- Явный adversarial framing в system prompt (не уклоняться в нейтральность — это работа PM)

**Слой 3 — Решающие:**
- **Portfolio Manager** — агрегирует дебат + контекст портфеля + thesis tracker → proposal (action/ticker/size/target/stop/horizon) + новый тезис
- **Risk Manager** — проверяет против hard limits (max position 15%, max sector 30%, daily loss budget) + soft checks (корреляция, просадка, волатильность индекса); **право вето**

### Граф (LangGraph)

```
trigger ─► fetch_data ─┬─ News ─────┐
                       ├─ Fund ─────┤
                       ├─ Technical ┼─► merge ─► [Bull ⇄ Bear debate]
                       └─ Sentiment ┘              (max 3 раунда,
                                                    early-exit on convergence)
                                                          │
                                              Portfolio Manager
                                                          │
                                                  Risk Manager ──VETO──► persist + "no signal"
                                                          │ APPROVE
                                              Telegram proposal + кнопки
                                                          │ user одобрил
                                              manual exec (Tinkoff) ─► Thesis save
```

Checkpoint после каждого узла → resume при сбое (не платим повторно за пройденные шаги).

### Триггеры агентного цикла

| Триггер | Скоуп | Частота | Полнота |
|---|---|---|---|
| Утренний дайджест (cron 9:00) | Позиции + top-3 watchlist | 1/день | аналитики + лёгкий PM, **без дебата** (экономия) |
| Conversation (`/ask`) | 1 тикер | по запросу | полный комитет |
| HIGH-impact news | тикер из портфеля/watchlist | реактивно | полный комитет |
| Thesis review | открытые позиции | weekly + при угрозе тезису | полный комитет |

### Сознательные ограничения
- Скрининг рынка — **алгоритмический** (RSI/breakout/volume), агенты только на топ-кандидатах
- Дебат ≤ 3 раунда; нет сходимости → PM решает с пометкой «no consensus»
- Прямого доступа агентов к ордерам нет — только через user approval

## 8. Память и Thesis Tracker

### Layered memory (FinMem-style)

| Слой | Хранит | TTL | Где |
|---|---|---|---|
| Working | State графа, последние ~10 сообщений | сессия | процесс + LangGraph checkpoint |
| Episodic | Сделки, анализы, high-impact новости, решения | 2 года | Postgres + pgvector |
| Reflective | Обобщённые уроки | бессрочно | Postgres + pgvector |

**Episodic:** каждое событие эмбеддится (text-embedding-3-small), индексируется HNSW. Семантический поиск «похожих сетапов» даже по разным тикерам.

**Reflective:** уроки генерит отдельный **Reflective Agent** (вс 23:00). Структура урока включает `times_applied` (естественный отбор: неиспользуемые архивируются, подтверждённые растят confidence).

### Thesis Tracker (механизм, не агент)
1. **Создание:** PM генерирует тезис как часть proposal (primary_drivers + invalidation_triggers + target + horizon + conviction). Сохраняется при одобрении.
2. **Мониторинг:** при новости по тикеру с активным тезисом — **Thesis Validator** (лёгкий LLM-запрос): `still_valid / weakened / invalidated`. `invalidated/weakened` → автозапуск полного цикла (для этого юзера это автоматически HIGH).
3. **Закрытие:** фиксируется итог (сработал/не сработал/нарушен) → корм для Reflective Agent.
4. **Импорт существующих позиций:** при onboarding ретроспективные тезисы (AI-реконструкция или ручной ввод) генерируются **только для активных крупных позиций** (дефолтный порог: ≥5% портфеля). Мелкие позиции пропускаются; их можно добавить вручную через `/thesis <ticker>` позже.

### Retrieval в агентный цикл
Memory Manager собирает контекст (recent episodes по тикеру + active thesis + семантически похожие ситуации + применимые insights с confidence ≥ 0.6), вставляет в `<memory>` system prompt. **Hard cap 2000 токенов**, обрезка по relevance.

## 9. Telegram UX

**Единственный интерфейс.** Reply Keyboard внизу: 📊 Портфель · 👁 Watchlist · 💡 Спросить · 📅 Дайджест · ⚙️ Настройки · ❓ Помощь.

**User commands:** `/start /portfolio /positions /thesis /watchlist /watch /unwatch /ask /scan /digest /history /insights /budget /settings /revoke /pause /resume /help`

**Admin commands:** `/admin invite|stats|users|user|revoke|set_budget|health`

**Ключевые flows:**
- **Утренний дайджест:** P&L портфеля + ночные новости + идеи дня + статус тезисов + календарь событий
- **HIGH-impact алерт:** двухступенчатый (мгновенно «комитет совещается» → через ~60 сек разбор + кнопки [Продать]/[Половину]/[Отложить]/[Отклонить]/[Полный разбор])
- **`/ask`:** прогон комитета, ответ с разбивкой по аналитикам + дебат + решение PM + опция алерта
- **`/thesis <ticker>`:** статус драйверов, invalidation triggers, target, хронология, кнопки редактирования/ре-оценки
- **Weekly reflection:** цифры недели + новый инсайт + что получалось/не получалось + применённые старые инсайты

**Approval / execution (f&f):** read-only токен → бот НЕ исполняет ордер. Показывает параметры, пользователь выставляет ордер вручную в Tinkoff app, подтверждает «выставил» → бот синхронит портфель и фиксирует тезис.

**FSM:** OnboardingFSM, TradeApprovalFSM, ThesisEditFSM, AskFSM.

**Quiet hours** (дефолт 22:00–08:00 МСК): HIGH копятся в буфер, приходят утром. **Throttling:** ≤3 алерта/час (слабые группируются). **Critical override:** уровень выше HIGH (напр. делистинг) — немедленно в любое время.

**Графики:** в MVP — ссылки на TradingView (`MOEX:TICKER`). Генерация картинок — V2.

**Вне скоупа:** inline mode, Mini App, группы/каналы, webhook (используем polling в MVP).

## 10. Мультитенантность

**Глобальный слой (1 копия):** News Watcher, market data через системный токен, universe IMOEX-40.
**Per-user слой:** Tinkoff токен (encrypted), портфель, watchlist, impact classification (контекстуально), память, Reflective Agent, budget, диалоги.

**Onboarding друга:** admin `/invite @user` → код (TTL 7 дней) → друг присылает код → инструкция по созданию **read-only** токена Tinkoff → присылает токен (бот шифрует, удаляет сообщение) → импорт портфеля + тезисы.

**Бюджет:** per-user monthly budget (дефолт $40). 80% → эконом-режим (mini вместо reasoning); 100% → тяжёлые циклы блокируются, остаются алерты. Admin видит глобальный дашборд.

**Изоляция:** все запросы фильтруются по `user_id` на уровне репозитория. F&F — это НЕ sharing данных: каждый видит только своё.

**Регуляторика:** f&f = personal use (серая, но безопасная зона). Публичный/платный запуск потребует лицензии — вне скоупа.

## 11. Безопасность и обработка ошибок

### Безопасность
- Только **read-only** токены Tinkoff в f&f-режиме
- Шифрование at rest (Fernet, ключ в env var); токен не логируется, не уходит в промпты; сообщение с токеном удаляется из чата
- `.env` в gitignore, pre-commit secret-scan; allow-list по telegram_id; admin-gate по role; Postgres только внутри Docker-сети
- Изоляция данных по user_id на уровне репозитория

### Главный AI-риск — галлюцинации в числах
- LLM **не источник** рыночных чисел: все цены/объёмы/P&L/размеры — только из Tinkoff API, кодом
- Агенты рассуждают о числах, но числа в proposal подставляются кодом из свежих данных
- Pydantic-валидация: size > баланса или target вне разумного диапазона без обоснования → флаг, не отправляется как есть

### Graceful degradation
| Сбой | Поведение |
|---|---|
| Tinkoff недоступен | Backoff (3 попытки) → кэш портфеля + пометка «устарело» |
| OpenAI rate-limit/5xx | Backoff + retry; checkpoint resume (без повторной оплаты шагов) |
| OpenAI лежит | Циклы в очередь; News Watcher копит; юзеру «разбор придёт позже» |
| Парсер сломан | Источник скипается; флаг в `/admin health` |
| Бюджет исчерпан | Тяжёлые циклы off, алерты по цене остаются |
| Битый токен | «Обнови токен», onboarding по новой |
| Невалидный JSON от LLM | Retry с уточнением (max 2) → честное «не смог, позже» |

**Принципы:** fail loud к админу, gracefully к юзеру; никаких тихих провалов (юзер всегда уведомлён); идемпотентность алертов (дедуп по url); circuit breaker на источниках.

### Наблюдаемость
- structlog (JSON), `/admin health` (статусы up/down, last success парсеров, queue depth, расход за день), `usage_log` (каждый LLM-вызов с cost), алерт админу при критических сбоях.

### Тестирование
- Tinkoff **sandbox** для dev; unit (валидаторы, изоляция, thesis-логика); integration (полный цикл на моках); eval-набор (10–15 исторических кейсов типа ВТБ-дивы) при изменении промптов; smoke на проде.
- Вне скоупа: 100% coverage, нагрузочное, сложный CI/CD.

## 12. Схема данных (PostgreSQL + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE NOT NULL,
    telegram_username VARCHAR(64),
    role VARCHAR(20) NOT NULL DEFAULT 'user',          -- 'admin'|'user'
    status VARCHAR(20) NOT NULL DEFAULT 'pending',     -- 'pending'|'active'|'suspended'
    tinkoff_token_encrypted BYTEA,
    monthly_budget_usd NUMERIC(8,2) DEFAULT 40,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invites (
    code VARCHAR(16) PRIMARY KEY,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    redeemed_by UUID REFERENCES users(id),
    redeemed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE watchlists (
    user_id UUID REFERENCES users(id),
    ticker VARCHAR(20),
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, ticker)
);

CREATE TABLE episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    ticker VARCHAR(20),
    event_type VARCHAR(50) NOT NULL,    -- trade_open|trade_close|analysis_run|news_high_impact|user_decision|thesis_invalidated|alert_triggered
    payload JSONB NOT NULL,
    embedding VECTOR(1536) NOT NULL
);
CREATE INDEX ON episodes (user_id, ticker, timestamp DESC);
CREATE INDEX ON episodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE theses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    ticker VARCHAR(20) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL,        -- active|closed|invalidated
    direction VARCHAR(10) NOT NULL,
    primary_drivers JSONB NOT NULL,
    invalidation_triggers JSONB NOT NULL,
    target_price NUMERIC,
    horizon VARCHAR(20),
    initial_conviction FLOAT,
    notes TEXT,
    realized_pnl NUMERIC,
    invalidation_reason TEXT
);
CREATE INDEX ON theses (user_id, ticker, status);

CREATE TABLE insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary TEXT NOT NULL,
    scope VARCHAR(50) NOT NULL,         -- ticker|sector|pattern|user_behavior|general
    scope_value VARCHAR(50),
    confidence FLOAT NOT NULL,
    supporting_episodes UUID[],
    embedding VECTOR(1536) NOT NULL,
    times_applied INTEGER DEFAULT 0,
    last_applied_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ
);
CREATE INDEX ON insights USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON insights (user_id, scope, scope_value, archived_at);

-- глобальные (shared, без user_id)
CREATE TABLE news_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(20),
    source VARCHAR(50),
    headline TEXT,
    body TEXT,
    url TEXT UNIQUE,
    embedding VECTOR(1536)
);

CREATE TABLE news_impacts (
    news_id UUID REFERENCES news_events(id),
    user_id UUID REFERENCES users(id),
    impact VARCHAR(20),                 -- critical|high|medium|low|noise
    direction VARCHAR(20),
    requires_action BOOLEAN,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (news_id, user_id)
);

CREATE TABLE usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    operation VARCHAR(50),
    model VARCHAR(50),
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd NUMERIC(10,6)
);
```

## 13. Cost engineering

- Полный цикл по 1 тикеру: ~$0.25–0.50
- Утренний дайджест без дебата (5–8 тикеров): ~$2–4/день
- Impact classification: ~$0.0005/новость (50 новостей/день ≈ $0.025)
- **Целевой per-user cost: $20–40/мес** (дебат только on-demand/HIGH, не каждое утро)
- Глобальный слой (embeddings новостей): ~$5–10/мес на всех
- Контроль: per-user budget cap, эконом-режим на 80%, блок тяжёлых циклов на 100%

## 14. План реализации (фазы)

| Фаза | Недели | Содержание | Артефакт |
|---|---|---|---|
| **0. Фундамент** | 1 | Repo, Docker, **smoke-тест Railway→Tinkoff API** (gate: при блокировке → Timeweb), Postgres+pgvector, Fernet, aiogram skeleton, Tinkoff connect, `/portfolio`, логи, error-каркас | Бот-«зеркало портфеля» |
| **1. Одиночный аналитик** | 2–3 | Парсеры RSS+Tinkoff news, 1 агент, `/ask`, утренний дайджест, universe IMOEX-40 | Превосходит платные TG-каналы |
| **2. Мультиагентный комитет** | 4–5 | LangGraph граф, 4 аналитика, Bull/Bear дебат, PM+Risk, approval flow, manual exec, cost-routing, usage_log | Уникальный на рынке РФ |
| **3. Память и тезисы** | 6–7 | Episodic memory + retrieval, Thesis Tracker + Validator, Reflective Agent + weekly reflection, импорт позиций | «Второй мозг» (вариант C достигнут) |
| **4. Реактивность + мультитенант** | 8–10 | News Watcher + Impact Classifier, HIGH-алерты, quiet hours/throttling, hard alerts, users/invites, per-user изоляция+budget, admin | F&F beta ready |

**~10 недель до полного продукта; полезные артефакты с конца недели 1.**

**Anti-burnout guardrails:** пауза «пожить» после каждой фазы; фазы 0–1 — must (дают рабочий бот + pitch); фазы 2+ — bonus, останов на любой; без преждевременной оптимизации.

## 15. Отложено (V2 / если будет нужно)

Auto-execute (trading-токен) · генерация графиков (matplotlib) · backtester · чтение заметок юзера · webhook вместо polling · web-дашборд · social/copy-trading.

## 16. Решённые вопросы (закрыты 2026-06-12)

1. **Reasoning-модели:** на ключе owner доступна вся линейка OpenAI → routing: o4-mini для дебатов/Risk, o3 для weekly reflection.
2. **Хостинг:** Railway (выбор owner). Первая задача Фазы 0 — smoke-тест подключения Railway → Tinkoff Invest API; при блокировке (санкционные/geo-фильтры) — fallback на Timeweb по готовому Docker Compose.
3. **Название:** **Roaring Kittens** (утверждено).
4. **Dev-окружение:** сразу dev на сервере (Railway dev environment / отдельный service), без локального VPN-сетапа.
5. **Импорт истории:** ретроспективные тезисы только для активных крупных позиций (≥5% портфеля); мелкие — вручную по желанию.
```

