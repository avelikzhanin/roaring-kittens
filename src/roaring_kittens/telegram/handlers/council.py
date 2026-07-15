from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from roaring_kittens.committee.render import format_council_protocol, format_council_verdict
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.db.council import get_council_transcript
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/council SBER</code> — полный разбор комитетом (4 аналитика + дебаты)."


@router.message(Command("council"))
async def cmd_council(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer("🏛 Комитет пока доступен только владельцу — "
                             "тебе доступен /ask ТИКЕР.")
        return
    if not command.args:
        await message.answer(USAGE)
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}». {USAGE}")
        return

    progress = await message.answer(
        f"🏛 Собираю комитет по {instrument.ticker}… (4 аналитика изучают данные)")
    try:
        async def on_stage(text: str) -> None:
            await progress.edit_text(text)

        outcome = await run_council_flow(deps, instrument, message.from_user.id,
                                         on_stage=on_stage)
    except Exception as exc:
        log.error("council_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Комитет по {instrument.ticker} сорвался — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/council {instrument.ticker}</code>")
        return

    keyboard = None
    if outcome.run_id is not None:
        buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                         callback_data=f"proto:{outcome.run_id}")]]
        if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
            buttons.append([InlineKeyboardButton(
                text="📌 Принять тезис", callback_data=f"thesis_save:{outcome.run_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await progress.edit_text(
        format_council_verdict(instrument.ticker, outcome.state["views"],
                               outcome.state["debate"], outcome.proposal, outcome.risk),
        reply_markup=keyboard)


@router.callback_query(F.data.startswith("proto:"))
async def cb_protocol(callback: CallbackQuery, deps: Deps) -> None:
    # Owner-гейт обязателен: в транскрипте (rationale/дебаты) может фигурировать
    # позиция владельца — гостям это видеть нельзя.
    owner_id = await fetch_owner_id(deps.session_factory)
    if callback.from_user.id != owner_id:
        await callback.answer("Протокол доступен только владельцу", show_alert=True)
        return
    await callback.answer()
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.message.answer("Протокол не найден.")
        return
    async with deps.session_factory() as session:
        transcript = await get_council_transcript(session, run_id)
    if transcript is None:
        await callback.message.answer("Протокол не найден.")
        return
    from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView
    views = [SpecialistView(**v) for v in transcript["views"]]
    proposal = Proposal(**transcript["proposal"])
    risk = RiskReview(**transcript["risk"])
    for chunk in format_council_protocol(views, transcript["debate"], proposal, risk):
        await callback.message.answer(chunk)
