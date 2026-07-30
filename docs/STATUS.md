# Roaring Kittens — статус проекта (обновлён 2026-07-30)

Хэндофф-файл для продолжения работы в любой сессии Claude Code.
Прочитай его + `docs/superpowers/specs/2026-06-04-roaring-kittens-design.md` перед работой.

## Что это

Telegram-бот — мультиагентный AI инвест-советник для Мосбиржи. Pet-проект +
portfolio piece для резюме AI PM. GitHub: https://github.com/avelikzhanin/roaring-kittens
(private). Прод: Railway (проект roaring-kittens, аккаунт Kamilla), бот жив.

## Состояние фаз

| Фаза | Статус | Тег |
|---|---|---|
| 0–1 Фундамент + одиночный аналитик | ✅ в проде | phase-0/phase-1 |
| 1.5 Trust Loop (calls → скоринг vs IMOEX → /track) | ✅ в проде | phase-1.5 |
| 2 Комитет (4 специалиста → Bull/Bear → PM → Risk, LangGraph) | ✅ в проде | phase-2 |
| 3 Память и тезисы (pgvector, авто-тезисы, валидатор, рефлексия) | ✅ в проде | phase-3 |
| 4a Реактивность (5-мин poll, impact, алерты, watchlist) + hardening | ✅ в проде | phase-4a |
| 4b Мультитенантность (invites, свои токены, бюджеты, per-user джобы) | ✅ в проде | phase-4b |
| 5 Сделки (идеи→[Беру]→авто-детект→уровни→сигналы→/deals) | ✅ в проде | phase-5 |
| 5.5 Сканер голубых фишек + глоссарий для розницы | ✅ в проде | phase-5.5 |

**Phase 4b (2026-07-22):** план прошёл адверсарное ревью (33 находки → 24 фикса в плане,
1 блокер — per-user гейт колбэков), исполнен батчами (13 задач), затем ретро-ревью КОДА
(16 находок → 12 исправлено, 1 отклонена, 3 дубля): изоляция сбоев отправки в джобах
(403 одного юзера не роняет цикл), revoked-фильтр в валидаторе тезисов, private-гейты
/digest и /admin (утечка portfolio_cache по chat.id в группе), скоупинг рефлексии и
/seed_retro, дометеривание embed_insight, отправка ПЕРЕД кулдауном/пометкой. 149 тестов.
Деплой: в логах schema_ensured(24) → owner_migrated_to_admin(215592311) → bot_starting.

**Phase 5 «Сделки» (2026-07-30):** ответ на вопрос юзера «как на этом зарабатывать» —
замкнута петля идея→действие→результат. Идеи ТОЛЬКО из approved-BUY комитета (guard
7 дней/тикер, TTL 48ч, «Пропущу» тоже глушит неделю); risk-based сайзинг (1% риска,
кап 15%, целые лоты из Tinkoff); PM даёт target/exit_price (санити-чек + фолбэк
−7/+14%); активация/закрытие — авто-детект по read-only счёту в positions_sync;
конвертация ЛЮБОЙ ничейной позиции в сделку; сигналы уровней в price_watch (в начале
джобы, до ранних return); /deals (private-only) с секциями «Ждут решения» (живые
кнопки после ночного буфера) / «Ждут покупки» / открытые / закрытые. Терминология:
«Инвалидация» → «🛑 Продаём если» везде. Новости: interfax добавлен в факты
(проверен в проде: fetched=25, inserted=3), smartlab → CROWD_SOURCES (только
сентимент комитета; вычищен из дайджеста, /ask, валидатора, impact). Дисклеймер
«не ИИР» в каждой идее. План ревьюился воркфлоу (21→13 фиксов, 1 блокер — двойное
покрытие тикера сделками). 160 тестов.

**Phase 5.5 (2026-07-30):** сканер голубых фишек — пн-пт 10:40 МСК: скрининг топ-10
IMOEX по весу (gpt-4o-mini ~$0.001/бумага) → полный комитет ТОЛЬКО по лучшему
(score≥70, ≤1/день); guards: council_run_recently по council_runs (видит
вето-прогоны, окно 7 дней), пропуск неторговых дней (последняя свеча < сегодня),
перезагрузка universe при пустых весах; идеи всем подключённым (source='scanner').
Глоссарий для розницы: «идея» — эксклюзивно сделки; тезисный слой = «причина
держать»/«сопровождение» («🎯 Суть:», кнопка «Взять на сопровождение», «Причина
держать X сломана/под вопросом», /thesis = «Почему держим», « · ещё не куплено»).
/help переписан вокруг сделок (+admin-блок). План ревьюился (13→10 фиксов).
162 теста.

**Следующий шаг:** E2E руками юзера: утренняя сверка сконвертирует SBER/VTBR в
сделки №1/№2 → /deals; в 10:40 лог scanner_screened (или scanner_skipped_non_trading_day);
/council по тикеру не из портфеля → идея → [Беру] → покупка → «Вижу покупку».
Затем E2E 4b (второй аккаунт, инвайт, бюджеты). Стратегическая рамка (обсуждена):
2-3 месяца копим track record сделок — потом решение про монетизацию.

## Конвенции проекта (устоявшиеся, не переспрашивать)

- **Исполнение планов:** inline (executing-plans), батчами; ветка на фичу → гранулярные
  коммиты → push → CI → ff-merge в master локально → ветку удалить → `railway up` → лог-чек.
- **Верификация:** локального Python/Docker НЕТ. Тесты только в GitHub Actions
  (`gh run watch`). 162 теста на 2026-07-30 (после Phase 5.5).
- **Деплой:** `railway up --service app --ci` из корня репо (PowerShell). Здоровье:
  `railway logs` → ждать `bot_starting`.
- **Планы:** через superpowers writing-plans, полный код в шагах, секция «отклонения от
  спеки»; после написания — адверсарное ревью, фиксы, потом код.
- **Коммиты:** `-c user.name="avelikzhanin"`, conventional commits, без Co-Authored-By.

## Критические gotcha

- **Tinkoff SDK удалён с PyPI**: ставится `pip install --no-deps "tinkoff-investments @
  git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta117"` (в CI и
  Dockerfile уже прошито). Namespace-shim `tinkoff` не нужен (PEP 420).
- **Railway приватная сеть** поднимается позже старта контейнера — ensure_schema имеет retry.
- **Postgres на Railway**: PGDATA=/var/lib/postgresql/data/pgdata (initdb ломался о lost+found).
- **HTML parse_mode**: любой LLM/новостной текст в сообщениях — через `esc()` из
  telegram/formatting.
- **Порядок свечей из API не гарантирован** — сортировать перед return_between/[-35:].
- Счёт владельца непустой (SBER, VTBR — по скриншотам 2026-07-16). Владелец 215592311
  мигрирован в users как admin (4b, идемпотентно на старте + в start.py при claim).

## Архитектурная карта (где что)

- `committee/` — комитет: runner.py (ядро, используется handler'ом и валидатором),
  graph.py (LangGraph), specialists/debate/manager/risk, memory.py (pgvector-память),
  thesis_gen/thesis_check, impact.py (классификатор новостей), render.py
- `scheduler.py` — все джобы: poll_news (5 мин) → validate_theses → impact_scan;
  digest 9:00; sync 8:50; скоринг 23:45; рефлексия вс 23:00; price_watch пн-пт 10-18;
  drain_pending 9-21ч
- `alerts.py` — quiet hours 22-08 МСК, per-chat троттлы 3/час, ночной буфер (at-least-once)
- `db/` — calls (общий track-record, asked_by; память/история/рефлексия скоупятся),
  theses (per-owner), insights, council_runs (asked_by гейтит колбэки), watchlist,
  alerts_buffer, users+invites (4b)
- 4b-ядро: `users_service.py` (get_user_broker c кэшем, статус ДО кэша; portfolio TTL 15м),
  `budget.py` (80%→econom, 100%→blocked), `ai/usage_context.py` (contextvars
  current_user_id/budget_mode — llm подменяет модель и пишет user_id в usage_log),
  `telegram/handlers/onboarding.py` (FSM токена, INV- 16hex, private-only),
  admin.py + budget_cmd.py
- Скоринг: вердикты vs IMOEX (MOEX ISS), горизонты 5/20/60д, hit = обогнал индекс

## Процессная статистика (для резюме-нарратива)

Адверсарные ревью поймали 95 реальных дефектов до/после кода: 1.5→5, 2→10 (2 блокера),
3→10 (1 блокер + латентный prod-баг HTML), 4a-ретро→11, 4b-план→24 (1 блокер),
4b-ретро→12 (1 блокер), 5-план→13 (1 блокер), 5.5-план→10. Продуктовый разбор
(12 агентов) породил Trust Loop; разбор недели живых логов с юзером породил
Phase 5 «Сделки» и сканер.
