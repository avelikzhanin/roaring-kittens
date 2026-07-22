from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.budget import budget_state
from roaring_kittens.db.users import get_user
from roaring_kittens.deps import Deps

router = Router()

STATE_ICON = {"ok": "🟢", "econom": "🟡", "blocked": "🔴"}
STATE_TEXT = {"ok": "всё доступно",
              "econom": "эконом-режим: разборы на облегчённых моделях",
              "blocked": "тяжёлые разборы заблокированы до 1-го числа"}


def format_budget(state: str, spent: Decimal, limit: Decimal) -> str:
    return (f"{STATE_ICON[state]} <b>AI-бюджет:</b> ${spent} из ${limit} за месяц\n"
            f"{STATE_TEXT[state]}")


@router.message(Command("budget"))
async def cmd_budget(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        user = await get_user(session, message.from_user.id)
    if user is None:  # гость: не пугаем «🔴 $0/$0»
        await message.answer("Бюджет считается после подключения по инвайт-коду. "
                             "Гостевой /ask — 10 запросов в день.")
        return
    state, spent, limit = await budget_state(deps, message.from_user.id)
    await message.answer(format_budget(state, spent, limit))
