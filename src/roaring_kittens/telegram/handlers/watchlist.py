from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.db.users import get_active_user
from roaring_kittens.db.watchlist import (
    add_to_watchlist, list_watchlist, remove_from_watchlist,
)
from roaring_kittens.deps import Deps

router = Router()

NOT_USER = ("🔒 Watchlist доступен подключённым пользователям "
            "(нужен инвайт-код от владельца).")


def format_watchlist(tickers: list[str]) -> str:
    if not tickers:
        return ("👁 Watchlist пуст.\n"
                "<code>/watch SBER</code> — следить за бумагой: impact-алерты по новостям "
                "и движение ≥5% за день.")
    lines = ["👁 <b>Watchlist:</b>", ""]
    lines += [f"• {t}" for t in tickers]
    lines += ["", "Убрать: <code>/unwatch ТИКЕР</code>"]
    return "\n".join(lines)


async def _active_user_or_none(message: Message, deps: Deps) -> int | None:
    """Watch не требует токена — алерты полезны и без портфеля."""
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        await message.answer(NOT_USER)
        return None
    return user.telegram_id


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, deps: Deps) -> None:
    user_id = await _active_user_or_none(message, deps)
    if user_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/watch SBER</code>")
        return
    instrument = deps.universe.resolve(command.args.split()[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{command.args.split()[0]}».")
        return
    async with deps.session_factory() as session:
        added = await add_to_watchlist(session, user_id, instrument.ticker)
        await session.commit()
    await message.answer(
        f"👁 {instrument.ticker} {'добавлен в watchlist' if added else 'уже в watchlist'}. "
        f"Алерты: значимые новости + движение ≥5% за день.")


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject, deps: Deps) -> None:
    user_id = await _active_user_or_none(message, deps)
    if user_id is None:
        return
    if not command.args:
        await message.answer("Формат: <code>/unwatch SBER</code>")
        return
    raw = command.args.split()[0]
    # резолвим алиасы так же, как /watch («сбер» -> SBER); незнакомое — как ввели
    instrument = deps.universe.resolve(raw)
    ticker = instrument.ticker if instrument else raw.upper()
    async with deps.session_factory() as session:
        removed = await remove_from_watchlist(session, user_id, ticker)
        await session.commit()
    await message.answer(f"👁 {ticker} {'убран' if removed else 'и не был в watchlist'}.")


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, deps: Deps) -> None:
    user_id = await _active_user_or_none(message, deps)
    if user_id is None:
        return
    async with deps.session_factory() as session:
        tickers = await list_watchlist(session, user_id)
    await message.answer(format_watchlist(tickers))
