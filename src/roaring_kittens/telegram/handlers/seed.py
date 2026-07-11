"""Ретро-посев: прогоняет аналитик по текущим позициям с as-of датой 60/30 дней назад
(только свечи, без новостей — их за прошлое не восстановить), сразу скорит.
Даёт видимый track-record в день 1 вместо дня 90. Стоимость ~2×N LLM-вызовов.
Идемпотентен: уже посеянные (тикер, as-of дата) пропускаются, поэтому перезапуск
после частичного сбоя безопасен, а накрутить track-record повторами нельзя."""
from datetime import datetime, timedelta, timezone

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.db.calls import get_retro_seeded_keys, save_call
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.scoring import score_due_calls

log = structlog.get_logger()
router = Router()

AS_OF_DAYS = (60, 30)
MAX_POSITIONS = 10


@router.message(Command("seed_retro"))
async def cmd_seed_retro(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer("🔒 Команда доступна только владельцу.")
        return
    async with deps.session_factory() as session:
        seeded_keys = await get_retro_seeded_keys(session)
    snap = await deps.broker.get_portfolio()
    if not snap.positions:
        await message.answer("Портфель пуст — сеять нечего.")
        return
    progress = await message.answer("🌱 Сею ретро-разборы (это ~1-2 минуты)…")
    now = datetime.now(tz=timezone.utc)
    seeded, skipped = 0, 0
    for pos in snap.positions[:MAX_POSITIONS]:
        try:
            candles = await deps.broker.get_daily_candles(pos.figi, days=150)
        except Exception as exc:
            log.warning("seed_candles_failed", ticker=pos.ticker, error=str(exc))
            continue
        candles = sorted(candles, key=lambda c: c.day)  # API-порядку не доверяем
        for days_ago in AS_OF_DAYS:
            as_of = now - timedelta(days=days_ago)
            if (pos.ticker, as_of.date()) in seeded_keys:
                skipped += 1
                continue
            past = [c for c in candles if c.day <= as_of.date()][-35:]
            tech = compute_tech_summary(past)
            if tech is None:
                continue
            try:
                report = await run_analyst(deps.llm, pos.ticker, tech, [], None)
            except Exception as exc:
                log.error("seed_analyst_failed", ticker=pos.ticker, error=str(exc))
                continue
            async with deps.session_factory() as session:
                await save_call(session, asked_by=owner_id, ticker=pos.ticker,
                                figi=pos.figi, source="retro", question=None,
                                stance=report.stance, confidence=report.confidence,
                                summary=report.summary, price_at_call=tech.last_close,
                                news_urls=[], created_at=as_of)
                await session.commit()
            seeded += 1
    scored = await score_due_calls(deps)
    await progress.edit_text(
        f"🌱 Посеяно {seeded} новых ретро-разборов "
        f"(пропущено существующих: {skipped}), оценено {scored}.\n"
        f"Смотри /track — у бота уже есть послужной список."
    )
