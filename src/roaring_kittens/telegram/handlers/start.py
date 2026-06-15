from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Портфель"), KeyboardButton(text="📅 Дайджест")],
        [KeyboardButton(text="💡 Спросить"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🐱📈 <b>Roaring Kittens</b>\n\n"
        "Я твой AI-аналитик по Мосбирже.\n"
        "Команды: /portfolio /ask /digest /help",
        reply_markup=MAIN_MENU,
    )
