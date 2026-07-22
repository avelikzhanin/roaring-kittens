from decimal import Decimal
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from roaring_kittens.db.calls import HistoryItem, get_ticker_history
from roaring_kittens.db.council import get_council_transcript
from roaring_kittens.db.insights import InsightRecord, list_active_insights
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import (
    ThesisRecord, close_thesis, get_active_theses, get_active_thesis, save_thesis,
)
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import STANCE_EMOJI, esc

log = structlog.get_logger()
router = Router()

NOT_OWNER = "🔒 Доступно только владельцу (данные привязаны к его портфелю и разборам)."


def format_theses(theses: list[ThesisRecord]) -> str:
    if not theses:
        return ("📌 Активных тезисов нет.\n"
                "Тезис появляется из /council (кнопка «Принять тезис») или "
                "автоматически для позиций ≥5% портфеля.")
    lines = ["📌 <b>Активные тезисы:</b>", ""]
    for t in theses:
        idea = "" if t.backed_by_position else " · идея"
        lines.append(f"<b>{t.ticker}</b> (с {t.opened_at:%d.%m}, {t.source}{idea})")
        lines.append(f"🎯 {esc(t.thesis)}")
        lines.append(f"🚨 Инвалидация: {esc(t.invalidation)}")
        lines.append("")
    lines.append("Каждая свежая новость по тикеру проверяет тезис автоматически.")
    return "\n".join(lines)


def format_insights(items: list[InsightRecord]) -> str:
    if not items:
        return ("💡 Уроков пока нет — они появляются из еженедельной рефлексии "
                "(вс 23:00), когда есть закрытые тезисы или оценённые разборы.")
    lines = ["💡 <b>Уроки бота:</b>", ""]
    for i in items[:15]:
        lines.append(f"• {esc(i.summary)}")
        lines.append(f"   [{i.scope}] уверенность {round(i.confidence*100)}% · "
                     f"применён {i.times_applied} раз")
    return "\n".join(lines)


def format_history(ticker: str, items: list[HistoryItem]) -> str:
    if not items:
        return f"🕰 По {ticker} разборов ещё не было."
    lines = [f"🕰 <b>История разборов {ticker}:</b>", ""]
    for h in items:
        score = ""
        if h.score_20d:
            sign = "+" if h.score_20d.excess_pp >= 0 else "−"
            score = (f" → 20д: {sign}{abs(h.score_20d.excess_pp)} пп "
                     f"({h.score_20d.verdict})")
        lines.append(f"{h.created_at:%d.%m} [{h.source}] {STANCE_EMOJI[h.stance]} "
                     f"{h.stance} {round(h.confidence*100)}%{score}")
        lines.append(f"   {esc(h.summary[:150])}")
    return "\n".join(lines)


@router.message(Command("thesis"))
async def cmd_thesis(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return
    async with deps.session_factory() as session:
        theses = await get_active_theses(session)
    await message.answer(format_theses(theses))


@router.message(Command("insights"))
async def cmd_insights(message: Message, deps: Deps) -> None:
    # owner-only: уроки выводятся из сделок владельца — могут раскрывать его результаты
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return
    async with deps.session_factory() as session:
        items = await list_active_insights(session)
    await message.answer(format_insights(items))


@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject, deps: Deps) -> None:
    # owner-only: summary council-разборов может содержать позицию владельца
    # (протокол комитета owner-gated ровно по этой причине)
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return
    if not command.args:
        await message.answer("Формат: <code>/history SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    async with deps.session_factory() as session:
        items = await get_ticker_history(session, instrument.ticker, limit=5)
    await message.answer(format_history(instrument.ticker, items))


@router.callback_query(F.data.startswith("thesis_save:"))
async def cb_thesis_save(callback: CallbackQuery, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with deps.session_factory() as session:
        transcript = await get_council_transcript(session, run_id)
    if not transcript or "meta" not in transcript:
        await callback.message.answer("Не нашёл данные комитета для тезиса.")
        return
    meta, proposal = transcript["meta"], transcript["proposal"]
    async with deps.session_factory() as session:
        # guard от двойного тапа/старой кнопки: тот же тезис не пересохраняем
        existing = await get_active_thesis(session, meta["ticker"])
        if existing and existing.thesis == proposal["thesis"]:
            await callback.message.answer("📌 Этот тезис уже принят. /thesis — все.")
            return
        entry = Decimal(meta["price_at_call"]) if meta.get("price_at_call") else None
        await save_thesis(session, ticker=meta["ticker"], figi=meta["figi"],
                          thesis=proposal["thesis"],
                          invalidation=proposal["invalidation"], source="council",
                          confidence=proposal["confidence"], entry_price=entry,
                          backed_by_position=meta.get("held", False),
                          owner_id=callback.from_user.id)
        await session.commit()
    await callback.message.answer(
        f"📌 Тезис по <b>{meta['ticker']}</b> принят:\n🎯 {esc(proposal['thesis'])}\n"
        f"🚨 {esc(proposal['invalidation'])}\n"
        f"Буду проверять его каждой новостью. /thesis — все.")


@router.callback_query(F.data.startswith("thesis_del:"))
async def cb_thesis_del(callback: CallbackQuery, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        thesis_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with deps.session_factory() as session:
        await close_thesis(session, thesis_id, status="closed",
                           realized_return_pct=None, close_reason="удалён владельцем")
        await session.commit()
    await callback.message.answer("🗑 Тезис закрыт.")
