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
from roaring_kittens.ai.usage_context import use_budget_mode, use_user
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.budget import HEAVY_BLOCKED_MSG, budget_state
from roaring_kittens.db.calls import get_retro_seeded_keys, save_call
from roaring_kittens.deps import Deps
from roaring_kittens.scoring import score_due_calls
from roaring_kittens.users_service import get_user_broker

log = structlog.get_logger()
router = Router()

AS_OF_DAYS = (60, 30)
MAX_POSITIONS = 10


@router.message(Command("seed_retro"))
async def cmd_seed_retro(message: Message, deps: Deps) -> None:
    owner_id = message.from_user.id
    broker = await get_user_broker(deps, owner_id)
    if broker is None:
        await message.answer("🔒 Нужен подключённый Tinkoff-токен "
                             "(инвайт-код от владельца).")
        return
    state, _, _ = await budget_state(deps, owner_id)
    if state == "blocked":
        await message.answer(HEAVY_BLOCKED_MSG)
        return
    mode = "econom" if state == "econom" else "ok"
    async with deps.session_factory() as session:
        # per-user: у второго юзера с тем же тикером свой посев
        seeded_keys = await get_retro_seeded_keys(session, asked_by=owner_id)
    snap = await broker.get_portfolio()
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
                with use_user(owner_id), use_budget_mode(mode):
                    report = await run_analyst(deps.llm, pos.ticker, tech, [], None)
            except Exception as exc:
                log.error("seed_analyst_failed", ticker=pos.ticker, error=str(exc))
                continue
            embedding = None
            try:
                with use_user(owner_id):
                    embedding = await deps.embedder.embed(
                        f"{pos.ticker} {report.stance}: {report.summary}",
                        operation="embed_call")
            except Exception as exc:
                log.warning("embed_call_failed", error=str(exc))
            async with deps.session_factory() as session:
                await save_call(session, asked_by=owner_id, ticker=pos.ticker,
                                figi=pos.figi, source="retro", question=None,
                                stance=report.stance, confidence=report.confidence,
                                summary=report.summary, price_at_call=tech.last_close,
                                news_urls=[], created_at=as_of, embedding=embedding)
                await session.commit()
            seeded += 1
    scored = await score_due_calls(deps)
    await progress.edit_text(
        f"🌱 Посеяно {seeded} новых ретро-разборов "
        f"(пропущено существующих: {skipped}), оценено {scored}.\n"
        f"Смотри /track — у бота уже есть послужной список."
    )
