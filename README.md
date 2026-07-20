# Roaring Kittens 🐱📈

Telegram-native AI investment co-pilot for MOEX (личный pet-проект).

**Сейчас (Phase 4a):** реактивность (5-мин News Watcher, Impact Classifier,
HIGH→авто-комитет, quiet hours, /watch, прайс-алерты ≥5%), память и тезисы,
мультиагентный комитет (`/council`), Trust Loop (`/track`), зеркало портфеля Tinkoff,
`/ask`, утренний дайджест.

**Дальше (Phase 4b):** мультитенантность для друзей (свои Tinkoff-токены, инвайты,
бюджеты). См. `docs/superpowers/specs/`.

## Команды бота

- `/ask TICKER [вопрос]` — AI-разбор бумаги (напр. `/ask SBER стоит докупать?`) — **доступно всем** (гости: 10/день)
- `/track` — послужной список бота: hit-rate vs IMOEX, включая худшие промахи — **доступно всем**
- `/portfolio` — портфель и P&L — **только владелец**
- `/digest` — дайджест сейчас — **только владелец**
- `/seed_retro` — ретро-посев track-record по позициям (60/30 дней назад) — **только владелец**
- `/start` — меню; **первый нажавший /start становится владельцем** (бот привязан к его счёту Tinkoff)

## Комитет (Phase 2)

`/council TICKER` (владелец): 4 специалиста параллельно (новости / техника /
дивиденды / настроения Smart-Lab) → adversarial дебаты Bull vs Bear (до 3 раундов,
ранний выход при сходимости) → Portfolio Manager (вердикт + тезис + триггер
инвалидации) → Risk Manager с правом вето (жёсткие лимиты кодом: концентрация >15%,
переуверенность на тонких данных). Оркестрация — LangGraph. Одобренные вердикты
пишутся в `calls` (source='council') и попадают в /track; вето — не пишутся.
Полный протокол дебатов — кнопкой «📜 Протокол» (владельцу). Прогон ~$0.2-0.4.

## Реактивность (Phase 4a)

Новости опрашиваются каждые 5 минут. Для тикеров с тезисом работает Thesis Validator;
для остальных тикеров портфеля и /watch-списка — Impact Classifier (gpt-4o-mini:
critical/high/medium/low/noise). HIGH → алерт + авто-комитет (≤1/сутки на тикер),
critical (делистинг, санкции на компанию, слом тезиса) — сквозь тихие часы и троттлинг.
Тихие часы 22:00–08:00 МСК: несрочное копится в буфер и приходит перед утренним
дайджестом. Троттлинг ≤3 алерта/час. Прайс-алерт: |движение| ≥5% от вчерашнего
закрытия (раз в день на тикер, торговые часы).

## Память и тезисы (Phase 3)

У каждой позиции ≥5% портфеля живёт тезис (авто-генерация или из /council кнопкой
«📌 Принять тезис»). Каждая РЕАЛЬНО новая новость по тикеру проверяет тезис (gpt-4o-mini):
invalidated → автозапуск комитета (≤1/сутки на тикер), закрытие тезиса и предложение
нового кнопкой. Ежедневный position-sync (08:50) закрывает тезисы проданных позиций
с фактическим результатом и помечает «идеи», ставшие позициями. Reflective Agent
(вс 23:00) извлекает уроки из закрытых тезисов и оценённых разборов; уроки и похожие
прошлые разборы подмешиваются комитету (pgvector + text-embedding-3-small).
Команды (владельцу): /thesis /insights /history.

## Trust Loop (Phase 1.5)

Каждый разбор сохраняется в `calls`; ночной джоб (23:45 МСК) оценивает вызовы
на горизонтах 5/20/60 дней против цены и IMOEX (bullish засчитывается, только
если бумага выросла И обогнала индекс). `/track` показывает hit-rate по ставкам,
средний результат vs IMOEX, бейзлайн и худшие промахи. Владельцу `/ask` отвечает
с учётом реальной позиции (шт/средняя/вес), а при смене мнения бот сам это флагает
(«🕰 Прошлый разбор: … → ⚠️ мнение изменилось»).

## Архитектура

- **Telegram:** aiogram 3, открытый доступ; владелец = первый `/start` (или `ADMIN_TELEGRAM_ID`, опционально); личные команды гейтятся по владельцу
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
3. Variables app-сервиса: `TELEGRAM_BOT_TOKEN`, `TINKOFF_TOKEN` (read-only!),
   `OPENAI_API_KEY`, `FERNET_KEY`, `DATABASE_URL`; опционально `ADMIN_TELEGRAM_ID`
   (фиксирует владельца заранее — иначе владелец = первый `/start`)
4. Применить схему: `railway run python scripts/apply_schema.py` → `SCHEMA OK`

`FERNET_KEY` сгенерировать: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
