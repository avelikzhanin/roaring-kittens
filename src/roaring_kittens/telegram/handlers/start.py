from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Портфель"), KeyboardButton(text="📅 Дайджест")],
        [KeyboardButton(text="💡 Спросить"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)

HELP_TEXT = (
    "🐱📈 <b>Roaring Kittens</b> — твой AI-аналитик по Мосбирже.\n\n"
    "<b>Команды:</b>\n"
    "• <code>/portfolio</code> — портфель и P&amp;L\n"
    "• <code>/ask ТИКЕР [вопрос]</code> — разбор бумаги\n"
    "   напр. <code>/ask SBER</code> или <code>/ask SBER стоит докупать?</code>\n"
    "• <code>/digest</code> — сводка сейчас\n\n"
    "Каждое утро в 9:00 МСК я сам пришлю дайджест по портфелю."
)

ASK_PROMPT = (
    "💡 Спроси меня о любой бумаге Мосбиржи.\n\n"
    "Напиши: <code>/ask ТИКЕР</code> — например <code>/ask GAZP</code>.\n"
    "Можно с вопросом: <code>/ask SBER стоит докупать?</code>"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🐱📈 <b>Roaring Kittens</b>\n\n"
        "Я твой AI-аналитик по Мосбирже.\n"
        "Команды: /portfolio /ask /digest /help",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=MAIN_MENU)


@router.message(F.text == "💡 Спросить")
async def btn_ask(message: Message) -> None:
    await message.answer(ASK_PROMPT)
