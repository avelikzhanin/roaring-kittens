from decimal import Decimal
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from roaring_kittens.db.calls import HistoryItem, get_ticker_history
from roaring_kittens.db.council import get_council_run
from roaring_kittens.db.insights import InsightRecord, list_active_insights
from roaring_kittens.db.theses import (
    ThesisRecord, close_thesis, get_active_theses, get_active_thesis, save_thesis,
)
from roaring_kittens.db.users import get_active_user
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import STANCE_EMOJI, esc

log = structlog.get_logger()
router = Router()

NOT_USER = ("🔒 Доступно подключённым пользователям "
            "(нужен инвайт-код от владельца).")
NOT_ADMIN = "🔒 Только для admin (уроки выводятся из его данных)."


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


async def _active_user(message: Message, deps: Deps):
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        await message.answer(NOT_USER)
    return user


@router.message(Command("thesis"))
async def cmd_thesis(message: Message, deps: Deps) -> None:
    user = await _active_user(message, deps)
    if user is None:
        return
    async with deps.session_factory() as session:
        theses = await get_active_theses(session, owner_id=user.telegram_id)
    await message.answer(format_theses(theses))


@router.message(Command("insights"))
async def cmd_insights(message: Message, deps: Deps) -> None:
    # admin-only: уроки выводятся из его закрытых тезисов (решение 3 плана 4b)
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None or user.role != "admin":
        await message.answer(NOT_ADMIN)
        return
    async with deps.session_factory() as session:
        items = await list_active_insights(session)
    await message.answer(format_insights(items))


@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject, deps: Deps) -> None:
    user = await _active_user(message, deps)
    if user is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/history SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    # свои разборы; admin видит все (summary чужих council-разборов ему можно)
    asked_by = None if user.role == "admin" else user.telegram_id
    async with deps.session_factory() as session:
        items = await get_ticker_history(session, instrument.ticker, limit=5,
                                         asked_by=asked_by)
    await message.answer(format_history(instrument.ticker, items))


@router.callback_query(F.data.startswith("thesis_save:"))
async def cb_thesis_save(callback: CallbackQuery, deps: Deps) -> None:
    uid = callback.from_user.id
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    async with deps.session_factory() as session:
        run = await get_council_run(session, run_id)
    if not run or "meta" not in run[0]:
        await callback.answer()
        await callback.message.answer("Не нашёл данные комитета для тезиса.")
        return
    transcript, asked_by = run
    if uid != asked_by:  # тезис из ЧУЖОГО прогона не принять — там чужая позиция
        await callback.answer("Кнопка инициатора разбора", show_alert=True)
        return
    await callback.answer()
    meta, proposal = transcript["meta"], transcript["proposal"]
    async with deps.session_factory() as session:
        # guard от двойного тапа/старой кнопки: тот же тезис не пересохраняем
        existing = await get_active_thesis(session, meta["ticker"], owner_id=uid)
        if existing and existing.thesis == proposal["thesis"]:
            await callback.message.answer("📌 Этот тезис уже принят. /thesis — все.")
            return
        entry = Decimal(meta["price_at_call"]) if meta.get("price_at_call") else None
        await save_thesis(session, ticker=meta["ticker"], figi=meta["figi"],
                          thesis=proposal["thesis"],
                          invalidation=proposal["invalidation"], source="council",
                          confidence=proposal["confidence"], entry_price=entry,
                          backed_by_position=meta.get("held", False),
                          owner_id=uid)
        await session.commit()
    await callback.message.answer(
        f"📌 Тезис по <b>{meta['ticker']}</b> принят:\n🎯 {esc(proposal['thesis'])}\n"
        f"🚨 {esc(proposal['invalidation'])}\n"
        f"Буду проверять его каждой новостью. /thesis — все.")


@router.callback_query(F.data.startswith("thesis_del:"))
async def cb_thesis_del(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    try:
        thesis_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with deps.session_factory() as session:
        # owner-условие в WHERE: чужой thesis_id молча не закроется
        await close_thesis(session, thesis_id, status="closed",
                           realized_return_pct=None, close_reason="удалён владельцем",
                           owner_id=callback.from_user.id)
        await session.commit()
    await callback.message.answer("🗑 Тезис закрыт.")
