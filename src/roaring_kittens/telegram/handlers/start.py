from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from roaring_kittens.db.owner import claim_owner, get_owner_id
from roaring_kittens.db.users import get_user, upsert_user
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.handlers.onboarding import (
    looks_like_invite, start_invite_redeem,
)

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Портфель"), KeyboardButton(text="📅 Дайджест")],
        [KeyboardButton(text="💡 Спросить"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)

HELP_TEXT = (
    "🐱📈 <b>Roaring Kittens</b> — AI-аналитик по Мосбирже.\n\n"
    "<b>Как спросить про бумагу (доступно всем):</b>\n"
    "• Жми «💡 Спросить» — покажу кнопки с тикерами, тап = разбор\n"
    "• Свой вопрос — руками: <code>/ask SBER почему падает?</code>\n"
    "• <code>/track</code> — послужной список бота (hit-rate vs IMOEX, включая промахи)\n\n"
    "<b>Для подключённых (инвайт-код + свой Tinkoff-токен):</b>\n"
    "• <code>/council ТИКЕР</code> — полный разбор комитетом (4 аналитика + дебаты Bull/Bear)\n"
    "• <code>/thesis</code> — активные тезисы · <code>/history ТИКЕР</code> — прошлые разборы\n"
    "• <code>/watch ТИКЕР</code> / <code>/unwatch</code> / <code>/watchlist</code> — "
    "алерты по новостям и движению ≥5%\n"
    "• <code>/portfolio</code> — портфель и P&amp;L · <code>/digest</code> — сводка\n"
    "• <code>/budget</code> — твой AI-бюджет · <code>/token</code> — сменить токен\n"
    "• Каждое утро в 9:00 МСК дайджест приходит сам."
)

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, deps: Deps,
                    state: FSMContext) -> None:
    async with deps.session_factory() as session:
        just_claimed = await claim_owner(session, message.from_user.id)
        owner_id = await get_owner_id(session)
        # Свежая инсталляция: /start ПОСЛЕ старта процесса — users-строка admin'а
        # создаётся сразу, не дожидаясь миграции при следующем рестарте.
        if owner_id == message.from_user.id and \
                await get_user(session, message.from_user.id) is None:
            await upsert_user(session, message.from_user.id,
                              username=message.from_user.username, role="admin")
        await session.commit()

    # deep-link: t.me/<bot>?start=INV-… — сразу в онбординг
    arg = (command.args or "").strip().upper()
    if arg and looks_like_invite(arg):
        await start_invite_redeem(message, deps, state, arg)
        return

    if just_claimed:
        intro = ("👑 Ты — владелец бота: /portfolio и утренний дайджест "
                 "привязаны к твоему счёту Tinkoff.")
    elif owner_id == message.from_user.id:
        intro = "С возвращением! 👑"
    else:
        intro = ("Я открыт для всех: спрашивай про любую бумагу Мосбиржи через /ask.\n"
                 "Есть инвайт-код от владельца? Просто пришли его сюда (формат INV-…) — "
                 "подключу твой портфель.")

    await message.answer(
        f"🐱📈 <b>Roaring Kittens</b>\n\nЯ AI-аналитик по Мосбирже.\n{intro}\n\n"
        "Команды: /ask /portfolio /digest /help",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=MAIN_MENU)
