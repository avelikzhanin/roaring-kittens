from datetime import date
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from roaring_kittens.committee.context import build_council_context
from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.render import format_council_protocol, format_council_verdict
from roaring_kittens.db.calls import save_call
from roaring_kittens.db.council import get_council_transcript, save_council_run
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/council SBER</code> — полный разбор комитетом (4 аналитика + дебаты)."


def _next_stage_text(node: str, state: dict, ticker: str) -> str | None:
    """astream(stream_mode='updates') стреляет ПОСЛЕ узла — анонсируем СЛЕДУЮЩУЮ стадию."""
    from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged
    if node == "specialists":
        return f"⚔️ {ticker}: аналитики высказались — дебаты Bull vs Bear…"
    if node == "bear":
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return f"👔 {ticker}: дебаты завершены — Portfolio Manager взвешивает…"
        return f"⚔️ {ticker}: дебаты, раунд {state['round'] + 1}…"
    if node == "manager":
        return f"🛡 {ticker}: Risk Manager проверяет…"
    return None


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
        ctx = await build_council_context(deps, instrument, message.from_user.id,
                                          today=date.today())
        graph = build_council_graph(deps.llm)
        state = {"ctx": ctx}
        async for chunk in graph.astream(state, stream_mode="updates"):
            for node, update in chunk.items():
                state.update(update)
                stage = _next_stage_text(node, state, instrument.ticker)
                if stage:
                    try:
                        await progress.edit_text(stage)
                    except Exception:  # too-fast identical edits — не критично
                        pass
        proposal, risk = state["proposal"], state["risk"]
    except Exception as exc:
        log.error("council_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Комитет по {instrument.ticker} сорвался — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/council {instrument.ticker}</code>")
        return

    call_id = run_id = None
    try:  # персист не должен ронять ответ
        async with deps.session_factory() as session:
            # Вето Risk = комитет НЕ дал рекомендацию → в track-record не пишем
            # (иначе заблокированная идея скорилась бы как реальная ставка).
            if risk.approved:
                call_id = await save_call(
                    session, asked_by=message.from_user.id, ticker=instrument.ticker,
                    figi=instrument.figi, source="council", question=None,
                    stance=proposal.stance, confidence=proposal.confidence,
                    summary=proposal.rationale,
                    price_at_call=ctx.tech.last_close if ctx.tech else None,
                    news_urls=[n.url for n in ctx.news_facts + ctx.crowd_posts])
            transcript = {
                "views": [v.model_dump() for v in state["views"]],
                "debate": state["debate"],
                "proposal": proposal.model_dump(),
                "risk": risk.model_dump(),
            }
            run_id = await save_council_run(session, ticker=instrument.ticker,
                                            asked_by=message.from_user.id,
                                            transcript=transcript, call_id=call_id)
            await session.commit()
    except Exception as exc:
        log.error("council_persist_failed", ticker=instrument.ticker, error=str(exc))

    keyboard = None
    if run_id is not None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📜 Протокол", callback_data=f"proto:{run_id}")]])
    await progress.edit_text(
        format_council_verdict(instrument.ticker, state["views"], state["debate"],
                               proposal, risk),
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
