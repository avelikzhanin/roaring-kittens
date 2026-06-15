# Roaring Kittens 🐱📈

Telegram-native AI investment co-pilot for MOEX (личный pet-проект).

**Сейчас (Phase 1):** зеркало портфеля Tinkoff, новостной пайплайн (RBC, Smart-Lab),
одиночный AI-аналитик (`/ask SBER`), утренний дайджест в 9:00 МСК.

**Дальше (Phases 2-4):** мультиагентный комитет (Bull/Bear-дебаты), память и тезисы,
HIGH-impact алерты, мультитенантность. См. `docs/superpowers/specs/`.

## Команды бота

- `/portfolio` — портфель и P&L
- `/ask TICKER [вопрос]` — AI-разбор бумаги (напр. `/ask SBER стоит докупать?`)
- `/digest` — дайджест сейчас
- `/start` — меню

## Архитектура

- **Telegram:** aiogram 3, allow-list по `ADMIN_TELEGRAM_ID`
- **Данные:** Tinkoff Invest gRPC SDK (портфель, свечи) + RSS (новости) → PostgreSQL 16 + pgvector
- **AI:** OpenAI structured outputs, расход пишется в `usage_log`
- **Universe:** IMOEX (состав через MOEX ISS) с маппингом тикер→FIGI из Tinkoff

> Tinkoff SDK ставится из git-тега (`RussianInvestments/invest-python`), т.к. удалён с PyPI;
> его namespace-shim `tinkoff` не нужен под PEP 420 — ставим `--no-deps` + реальные зависимости.

## Dev

Тесты гоняются в GitHub Actions CI (Python 3.12 + Postgres service container).
Локально (опционально, нужен Python 3.12 + Docker):

```
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
pip install --no-deps "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta117"
docker compose up -d db
python -m pytest                      # юнит-тесты (integration пропустятся)
# для integration-тестов БД:
set TEST_DATABASE_URL=postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test
docker compose exec db psql -U kittens -c "CREATE DATABASE kittens_test"
python -m pytest
```

## Deploy (Railway)

1. Подключить репо к Railway (Dockerfile определится автоматически)
2. Добавить Postgres-сервис (image `pgvector/pgvector:pg16`) с volume
3. Variables app-сервиса: `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `TINKOFF_TOKEN`
   (read-only!), `OPENAI_API_KEY`, `FERNET_KEY`, `DATABASE_URL`
4. Применить схему: `railway run python scripts/apply_schema.py` → `SCHEMA OK`

`FERNET_KEY` сгенерировать: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
