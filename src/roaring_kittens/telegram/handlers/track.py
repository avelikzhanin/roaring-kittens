from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from roaring_kittens.db.calls import count_unscored, get_scored_calls
from roaring_kittens.deps import Deps
from roaring_kittens.scoring import build_track_stats
from roaring_kittens.telegram.formatting import format_track

router = Router()


@router.message(Command("track"))
async def cmd_track(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        rows = await get_scored_calls(session)
        unscored = await count_unscored(session)
    await message.answer(format_track(build_track_stats(rows), unscored=unscored))
