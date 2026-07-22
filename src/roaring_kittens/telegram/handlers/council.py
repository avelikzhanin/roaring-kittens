from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from roaring_kittens.ai.usage_context import use_budget_mode, use_user
from roaring_kittens.budget import HEAVY_BLOCKED_MSG, budget_state
from roaring_kittens.committee.render import format_council_protocol, format_council_verdict
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.db.council import get_council_run
from roaring_kittens.db.users import get_active_user
from roaring_kittens.deps import Deps
from roaring_kittens.users_service import get_user_broker

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/council SBER</code> — полный разбор комитетом (4 аналитика + дебаты)."


@router.message(Command("council"))
async def cmd_council(message: Message, command: CommandObject, deps: Deps) -> None:
    uid = message.from_user.id
    broker = await get_user_broker(deps, uid)
    if broker is None:
        await message.answer("🏛 Комитет доступен подключённым пользователям "
                             "(инвайт-код + свой Tinkoff-токен) — тебе доступен /ask ТИКЕР.")
        return
    state, _, _ = await budget_state(deps, uid)
    if state == "blocked":
        await message.answer(HEAVY_BLOCKED_MSG)
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

        with use_user(uid), use_budget_mode("econom" if state == "econom" else "ok"):
            outcome = await run_council_flow(deps, instrument, uid,
                                             on_stage=on_stage, broker=broker)
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


async def _may_see_run(deps: Deps, user_id: int, asked_by: int) -> bool:
    """Транскрипт содержит позицию инициатора: только он сам или admin."""
    if user_id == asked_by:
        return True
    async with deps.session_factory() as session:
        user = await get_active_user(session, user_id)
    return user is not None and user.role == "admin"


@router.callback_query(F.data.startswith("proto:"))
async def cb_protocol(callback: CallbackQuery, deps: Deps) -> None:
    try:
        run_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Протокол не найден.", show_alert=True)
        return
    async with deps.session_factory() as session:
        run = await get_council_run(session, run_id)
    if run is None:
        await callback.answer("Протокол не найден.", show_alert=True)
        return
    transcript, asked_by = run
    if not await _may_see_run(deps, callback.from_user.id, asked_by):
        await callback.answer("Протокол доступен только инициатору разбора",
                              show_alert=True)
        return
    await callback.answer()
    from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView
    views = [SpecialistView(**v) for v in transcript["views"]]
    proposal = Proposal(**transcript["proposal"])
    risk = RiskReview(**transcript["risk"])
    for chunk in format_council_protocol(views, transcript["debate"], proposal, risk):
        await callback.message.answer(chunk)
