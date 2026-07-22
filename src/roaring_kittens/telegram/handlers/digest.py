from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.ai.usage_context import use_budget_mode, use_user
from roaring_kittens.budget import budget_state
from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest
from roaring_kittens.users_service import get_user_broker

router = Router()

NO_BROKER = ("🔒 Дайджест строится по твоему портфелю — нужен подключённый "
             "Tinkoff-токен (инвайт-код от владельца).\n"
             "Тебе доступен /ask — разбор любой бумаги Мосбиржи.")


@router.message(Command("digest"))
@router.message(F.text == "📅 Дайджест")
async def cmd_digest(message: Message, deps: Deps) -> None:
    broker = await get_user_broker(deps, message.from_user.id)
    if broker is None:
        await message.answer(NO_BROKER)
        return
    await message.answer("⏳ Собираю дайджест…")
    uid = message.from_user.id
    state, _, _ = await budget_state(deps, uid)
    mode = "econom" if state in ("econom", "blocked") else "ok"
    with use_user(uid), use_budget_mode(mode):
        await run_morning_digest(deps, message.bot, message.chat.id, broker=broker,
                                 allow_spotlight=state != "blocked")
