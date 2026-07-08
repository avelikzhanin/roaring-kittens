from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import format_portfolio

router = Router()

NOT_OWNER = ("🔒 Портфель привязан к счёту владельца бота и виден только ему.\n"
             "Тебе доступен /ask — разбор любой бумаги Мосбиржи.")


@router.message(Command("portfolio"))
@router.message(F.text == "📊 Портфель")
async def cmd_portfolio(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None or message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return
    snap = await deps.broker.get_portfolio()
    await message.answer(format_portfolio(snap))
