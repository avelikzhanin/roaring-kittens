from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest

router = Router()

NOT_OWNER = ("🔒 Дайджест строится по портфелю владельца бота и доступен только ему.\n"
             "Тебе доступен /ask — разбор любой бумаги Мосбиржи.")


@router.message(Command("digest"))
@router.message(F.text == "📅 Дайджест")
async def cmd_digest(message: Message, deps: Deps) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None or message.from_user.id != owner_id:
        await message.answer(NOT_OWNER)
        return
    await message.answer("⏳ Собираю дайджест…")
    await run_morning_digest(deps, message.bot, message.chat.id)
