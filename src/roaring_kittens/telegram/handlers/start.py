from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from roaring_kittens.db.owner import claim_owner, get_owner_id
from roaring_kittens.deps import Deps

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
    "<b>Только для владельца:</b>\n"
    "• <code>/portfolio</code> — портфель и P&amp;L\n"
    "• <code>/digest</code> — сводка по портфелю\n"
    "• Каждое утро в 9:00 МСК дайджест приходит сам."
)

@router.message(CommandStart())
async def cmd_start(message: Message, deps: Deps) -> None:
    async with deps.session_factory() as session:
        just_claimed = await claim_owner(session, message.from_user.id)
        await session.commit()
        owner_id = await get_owner_id(session)

    if just_claimed:
        intro = ("👑 Ты — владелец бота: /portfolio и утренний дайджест "
                 "привязаны к твоему счёту Tinkoff.")
    elif owner_id == message.from_user.id:
        intro = "С возвращением! 👑"
    else:
        intro = ("Я открыт для всех: спрашивай про любую бумагу Мосбиржи через /ask.\n"
                 "Портфель и дайджест доступны только владельцу бота.")

    await message.answer(
        f"🐱📈 <b>Roaring Kittens</b>\n\nЯ AI-аналитик по Мосбирже.\n{intro}\n\n"
        "Команды: /ask /portfolio /digest /help",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=MAIN_MENU)
