from datetime import datetime, timedelta, timezone

import structlog
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.telegram.formatting import format_analyst_report

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/ask SBER</code> или <code>/ask SBER стоит докупать?</code>"


LIMIT_REACHED = ("⏳ Лимит запросов на сегодня исчерпан ({limit}/день для гостей). "
                 "Приходи завтра!")


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer(USAGE)
        return
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id and not deps.ask_limiter.allow(message.from_user.id):
        await message.answer(LIMIT_REACHED.format(limit=deps.ask_limiter.limit))
        return
    parts = command.args.split(maxsplit=1)
    instrument = deps.universe.resolve(parts[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{parts[0]}». {USAGE}")
        return
    question = parts[1] if len(parts) > 1 else None

    progress = await message.answer(f"🤖 Анализирую {instrument.ticker}…")
    try:
        candles = await deps.broker.get_daily_candles(instrument.figi)
        tech = compute_tech_summary(candles)
        since = datetime.now(tz=timezone.utc) - timedelta(days=3)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [instrument.ticker], since=since)
        report = await run_analyst(deps.llm, instrument.ticker, tech, news, question)
    except Exception as exc:
        log.error("ask_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Не смог разобрать {instrument.ticker} — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/ask {instrument.ticker}</code>"
        )
        return

    low_data = tech is None or not news
    await progress.edit_text(
        format_analyst_report(report, low_data=low_data, sources=news or None)
    )
