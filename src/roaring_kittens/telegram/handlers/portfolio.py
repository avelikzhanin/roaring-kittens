from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.deps import Deps
from roaring_kittens.telegram.formatting import format_portfolio

router = Router()


@router.message(Command("portfolio"))
@router.message(F.text == "📊 Портфель")
async def cmd_portfolio(message: Message, deps: Deps) -> None:
    snap = await deps.broker.get_portfolio()
    await message.answer(format_portfolio(snap))
