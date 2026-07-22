# Roaring Kittens — статус проекта (обновлён 2026-07-22, вечер)

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

**Phase 4b (2026-07-22):** план прошёл адверсарное ревью (33 находки → 24 фикса в плане,
1 блокер — per-user гейт колбэков), исполнен батчами (13 задач), затем ретро-ревью КОДА
(16 находок → 12 исправлено, 1 отклонена, 3 дубля): изоляция сбоев отправки в джобах
(403 одного юзера не роняет цикл), revoked-фильтр в валидаторе тезисов, private-гейты
/digest и /admin (утечка portfolio_cache по chat.id в группе), скоупинг рефлексии и
/seed_retro, дометеривание embed_insight, отправка ПЕРЕД кулдауном/пометкой. 149 тестов.
Деплой: в логах schema_ensured(24) → owner_migrated_to_admin(215592311) → bot_starting.

**Следующий шаг:** E2E-чеклист Task 13 плана 4b руками юзера: /admin invite → онбординг
со второго аккаунта → изоляция /thesis и /portfolio → /admin set_budget 1 → блок комитета →
/admin revoke. Юзер обещал скидывать ответы бота для совместного анализа.

## Конвенции проекта (устоявшиеся, не переспрашивать)

- **Исполнение планов:** inline (executing-plans), батчами; ветка на фичу → гранулярные
  коммиты → push → CI → ff-merge в master локально → ветку удалить → `railway up` → лог-чек.
- **Верификация:** локального Python/Docker НЕТ. Тесты только в GitHub Actions
  (`gh run watch`). 149 тестов на 2026-07-22 (после 4b).
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

Адверсарные ревью поймали 72 реальных дефекта до/после кода: 1.5→5, 2→10 (2 блокера),
3→10 (1 блокер + латентный prod-баг HTML), 4a-ретро→11, 4b-план→24 (1 блокер),
4b-ретро→12 (1 блокер). Продуктовый разбор (12 агентов) породил Trust Loop —
главный дифференциатор.
