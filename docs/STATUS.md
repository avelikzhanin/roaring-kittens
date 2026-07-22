# Roaring Kittens — статус проекта (обновлён 2026-07-22)

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
| 4b Мультитенантность | 📋 план написан, НЕ ревьюился, НЕ исполнялся | — |

**Следующий шаг:** адверсарное ревью плана `docs/superpowers/plans/2026-07-21-phase-4b-multitenancy.md`
(воркфлоу: 3 ревьюера; верификацию находок делать ВРУЧНУЮ — verify-агенты дважды упирались
в session limit) → фиксы плана → inline-исполнение батчами. В плане 4b Task 6 УЖЕ сделан
(per-chat троттлы, hardening 2026-07-22) — пропустить.

## Конвенции проекта (устоявшиеся, не переспрашивать)

- **Исполнение планов:** inline (executing-plans), батчами; ветка на фичу → гранулярные
  коммиты → push → CI → ff-merge в master локально → ветку удалить → `railway up` → лог-чек.
- **Верификация:** локального Python/Docker НЕТ. Тесты только в GitHub Actions
  (`gh run watch`). 130 тестов на 2026-07-22.
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
- Счёт владельца непустой (SBER, VTBR — по скриншотам 2026-07-16). Владелец в bot_state,
  станет admin при миграции 4b.

## Архитектурная карта (где что)

- `committee/` — комитет: runner.py (ядро, используется handler'ом и валидатором),
  graph.py (LangGraph), specialists/debate/manager/risk, memory.py (pgvector-память),
  thesis_gen/thesis_check, impact.py (классификатор новостей), render.py
- `scheduler.py` — все джобы: poll_news (5 мин) → validate_theses → impact_scan;
  digest 9:00; sync 8:50; скоринг 23:45; рефлексия вс 23:00; price_watch пн-пт 10-18;
  drain_pending 9-21ч
- `alerts.py` — quiet hours 22-08 МСК, per-chat троттлы 3/час, ночной буфер (at-least-once)
- `db/` — calls (общий track-record, asked_by), theses (тезисы, backed/idea), insights,
  council_runs (транскрипты), watchlist, alerts_buffer, users (план 4b)
- Скоринг: вердикты vs IMOEX (MOEX ISS), горизонты 5/20/60д, hit = обогнал индекс

## Процессная статистика (для резюме-нарратива)

Адверсарные ревью поймали 36 реальных дефектов до/после кода: 1.5→5, 2→10 (2 блокера),
3→10 (1 блокер + латентный prod-баг HTML), 4a-ретро→11. Продуктовый разбор (12 агентов)
породил Trust Loop — главный дифференциатор.
