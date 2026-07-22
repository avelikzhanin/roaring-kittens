from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import format_portfolio
from roaring_kittens.users_service import get_user_broker

router = Router()

NO_BROKER = ("🔒 Портфель доступен после подключения своего Tinkoff-токена "
             "(нужен инвайт-код от владельца).\n"
             "Тебе доступен /ask — разбор любой бумаги Мосбиржи.")


@router.message(Command("portfolio"))
@router.message(F.text == "📊 Портфель")
async def cmd_portfolio(message: Message, deps: Deps) -> None:
    broker = await get_user_broker(deps, message.from_user.id)
    if broker is None:
        await message.answer(NO_BROKER)
        return
    snap = await broker.get_portfolio()
    await message.answer(format_portfolio(snap))
