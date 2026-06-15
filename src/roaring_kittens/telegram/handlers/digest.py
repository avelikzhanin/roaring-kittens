from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest

router = Router()


@router.message(Command("digest"))
@router.message(F.text == "📅 Дайджест")
async def cmd_digest(message: Message, deps: Deps) -> None:
    await message.answer("⏳ Собираю дайджест…")
    await run_morning_digest(deps, message.bot, message.chat.id)
