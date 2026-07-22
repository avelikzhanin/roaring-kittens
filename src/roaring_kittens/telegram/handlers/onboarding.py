"""Онбординг друга: инвайт-код -> инструкция -> приём токена (сообщение удаляется).

Всё ТОЛЬКО в личке (F.chat.type == "private") — токен в группе недопустим."""
import re
import secrets

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from roaring_kittens.db.users import (
    get_active_user, redeem_invite, set_user_token, upsert_user,
)
from roaring_kittens.deps import Deps
from roaring_kittens.security.crypto import encrypt_secret
from roaring_kittens.users_service import get_user_broker, invalidate_user_broker
from roaring_kittens.utils.ratelimit import DailyLimiter

log = structlog.get_logger()
router = Router()

INVITE_RE = re.compile(r"^INV-[A-F0-9]{16}$", re.IGNORECASE)
TOKEN_RE = re.compile(r"^t\.[A-Za-z0-9_\-]{16,}$")

# Подбор кодов: формат-валидных попыток мало у честного юзера, много у брутфорса
_redeem_limiter = DailyLimiter(10)


class Onboarding(StatesGroup):
    waiting_token = State()


def generate_invite_code() -> str:
    return "INV-" + secrets.token_hex(8).upper()   # 16 hex = 2^64


def looks_like_invite(text: str) -> bool:
    return bool(INVITE_RE.match(text.strip()))


def looks_like_tinkoff_token(text: str) -> bool:
    return bool(TOKEN_RE.match(text.strip()))


TOKEN_INSTRUCTIONS = (
    "✅ Код принят! Чтобы я работал с ТВОИМ портфелем, нужен токен Tinkoff Invest API:\n\n"
    "1. Открой tbank.ru/invest → Настройки → «Токен Tinkoff Invest API»\n"
    "2. Тип: <b>«Только чтение»</b> (я по дизайну не совершаю сделок)\n"
    "3. Скопируй токен (вида <code>t.XXXX…</code>) и пришли сюда одним сообщением\n\n"
    "🔒 Токен шифруется, сообщение с ним я сразу удалю. Передумал — /cancel."
)


async def start_invite_redeem(message: Message, deps: Deps, state: FSMContext,
                              code: str) -> None:
    """Общее тело для присланного кода и deep-link /start INV-… ."""
    if not _redeem_limiter.allow(message.from_user.id):
        await message.answer("⏳ Слишком много попыток — попробуй завтра.")
        return
    async with deps.session_factory() as session:
        ok = await redeem_invite(session, code, message.from_user.id)
        if ok:  # upsert реактивирует revoked (status='active' в set_)
            await upsert_user(session, message.from_user.id,
                              username=message.from_user.username)
        await session.commit()
    if not ok:
        await message.answer("❌ Код не найден, просрочен или уже использован.")
        return
    await state.set_state(Onboarding.waiting_token)
    await message.answer(TOKEN_INSTRUCTIONS)


@router.message(F.chat.type == "private", F.text.regexp(r"(?i)^INV-[A-F0-9]{16}$"))
async def handle_invite_code(message: Message, deps: Deps, state: FSMContext) -> None:
    await start_invite_redeem(message, deps, state, message.text.strip().upper())


@router.message(Onboarding.waiting_token, Command("cancel"))
async def cancel_onboarding(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок, отменил. Аккаунт создан без портфеля — /ask доступен. "
                         "Захочешь подключить счёт — просто пришли /token.")


@router.message(Command("token"))
async def cmd_token(message: Message, deps: Deps, state: FSMContext) -> None:
    """Повторный вход в приём токена: после /cancel или для ротации. Инвайт гейтит
    только ПЕРВУЮ регистрацию — существующему active-юзеру код заново не нужен."""
    if message.chat.type != "private":
        return
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        await message.answer("Сначала нужен инвайт-код от владельца (формат INV-…).")
        return
    await state.set_state(Onboarding.waiting_token)
    await message.answer(TOKEN_INSTRUCTIONS)


@router.message(Onboarding.waiting_token)
async def handle_token(message: Message, deps: Deps, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        # команды не глотаем молча: FSM-state перехватывает всё — подскажем выход
        await message.answer("Сейчас жду токен. Пришли его или /cancel — "
                             "потом команды снова заработают.")
        return
    if not looks_like_tinkoff_token(text):
        await message.answer("Не похоже на токен (ожидаю <code>t.XXXX…</code>). "
                             "Попробуй ещё раз или /cancel.")
        return
    try:
        await message.delete()  # токен не должен остаться в чате
    except Exception as exc:
        # Не смогли удалить — токен НЕ сохраняем: он остался в переписке
        log.error("token_message_delete_failed", error=str(exc))
        await message.answer("⚠️ Не смог удалить сообщение с токеном — он остался в чате. "
                             "Этот токен НЕ сохранён: отзови его в настройках Tinkoff, "
                             "выпусти новый и пришли ещё раз.")
        return
    encrypted = encrypt_secret(text, deps.settings.fernet_key)
    async with deps.session_factory() as session:
        await set_user_token(session, message.from_user.id, encrypted)
        await session.commit()
    invalidate_user_broker(deps, message.from_user.id)
    broker = await get_user_broker(deps, message.from_user.id)
    try:
        snap = await broker.get_portfolio()
        positions = ", ".join(p.ticker for p in snap.positions) or "пусто"
    except Exception as exc:
        log.error("onboarding_portfolio_failed", error=str(exc))
        async with deps.session_factory() as session:
            await set_user_token(session, message.from_user.id, None)
            await session.commit()
        invalidate_user_broker(deps, message.from_user.id)
        await message.answer("❌ Токен не сработал (проверь, что он Invest API и активен). "
                             "Пришли другой или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"🎉 Подключился к твоему счёту! Позиции: {positions}.\n\n"
        f"Тебе доступно: /portfolio /digest /ask /thesis /watch /budget.\n"
        f"Утренний дайджест — сам в 9:00 МСК. Тезисы для позиций ≥5% появятся "
        f"после ближайшей утренней сверки.")


@router.message(F.chat.type == "private", F.text.regexp(r"^t\.[A-Za-z0-9_\-]{16,}$"))
async def stray_token(message: Message, deps: Deps, state: FSMContext) -> None:
    """Токен вне FSM (MemoryStorage сбросился на редеплое / юзер прислал без /token).
    Сообщение удаляем ВСЕГДА; известному active-юзеру — обрабатываем как submission."""
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer("Похоже на токен! Но сначала нужен инвайт-код (INV-…). "
                             "Токен на всякий случай удалил — после кода пришлёшь новый.")
        return
    await state.set_state(Onboarding.waiting_token)
    await handle_token(message, deps, state)
