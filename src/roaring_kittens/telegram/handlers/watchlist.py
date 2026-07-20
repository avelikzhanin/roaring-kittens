from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.watchlist import (
    add_to_watchlist, list_watchlist, remove_from_watchlist,
)
from roaring_kittens.deps import Deps

router = Router()

NOT_OWNER = "🔒 Watchlist доступен только владельцу — алерты по нему идут владельцу."


def format_watchlist(tickers: list[str]) -> str:
    if not tickers:
        return ("👁 Watchlist пуст.\n"
                "<code>/watch SBER</code> — следить за бумагой: impact-алерты по новостям "
                "и движение ≥5% за день.")
    lines = ["👁 <b>Watchlist:</b>", ""]
    lines += [f"• {t}" for t in tickers]
    lines += ["", "Убрать: <code>/unwatch ТИКЕР</code>"]
    return "\n".join(lines)


async def _owner_or_none(message: Message, deps: Deps) -> int | None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return None
    return owner_id


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/watch SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    async with deps.session_factory() as session:
        added = await add_to_watchlist(session, owner_id, instrument.ticker)
        await session.commit()
    await message.answer(
        f"👁 {instrument.ticker} {'добавлен в watchlist' if added else 'уже в watchlist'}. "
        f"Алерты: значимые новости + движение ≥5% за день.")


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/unwatch SBER</code>")
        return
    ticker = command.args.split()[0].upper()
    async with deps.session_factory() as session:
        removed = await remove_from_watchlist(session, owner_id, ticker)
        await session.commit()
    await message.answer(f"👁 {ticker} {'убран' if removed else 'и не был в watchlist'}.")


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, deps: Deps) -> None:
    owner_id = await _owner_or_none(message, deps)
    if owner_id is None:
        return
    async with deps.session_factory() as session:
        tickers = await list_watchlist(session, owner_id)
    await message.answer(format_watchlist(tickers))
