from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from roaring_kittens.db.users import (
    UserRecord, create_invite, get_user, list_active_users, month_spend,
    set_user_budget, set_user_status, set_user_token,
)
from roaring_kittens.deps import Deps
from roaring_kittens.telegram.handlers.onboarding import generate_invite_code
from roaring_kittens.users_service import invalidate_user_broker

router = Router()

USAGE = ("/admin invite — создать код\n"
         "/admin users — юзеры и расходы\n"
         "/admin revoke ID — отключить\n"
         "/admin set_budget ID USD — лимит")


def format_users(users: list[UserRecord], spend: dict[int, Decimal]) -> str:
    lines = ["👥 <b>Пользователи:</b>", ""]
    for u in users:
        token = "🔑" if u.has_token else "—"
        lines.append(f"{u.telegram_id} @{u.username or '?'} [{u.role}] {token} "
                     f"${spend.get(u.telegram_id, Decimal('0'))}/"
                     f"${u.monthly_budget_usd}")
    return "\n".join(lines)


async def _require_admin(message: Message, deps: Deps) -> bool:
    async with deps.session_factory() as session:
        user = await get_user(session, message.from_user.id)
    if user is None or user.role != "admin" or user.status != "active":
        await message.answer("🔒 Только для admin.")
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    if message.chat.type != "private":
        return  # инвайт-коды и роспись юзеров в группу не публикуем
    if not await _require_admin(message, deps):
        return
    args = (command.args or "").split()
    if not args:
        await message.answer(USAGE)
        return
    sub = args[0]
    async with deps.session_factory() as session:
        if sub == "invite":
            code = generate_invite_code()
            await create_invite(session, code, created_by=message.from_user.id)
            await session.commit()
            me = await message.bot.get_me()
            await message.answer(
                f"🎟 Код (7 дней): <code>{code}</code>\n"
                f"Друг просто отправляет его боту, или по ссылке:\n"
                f"https://t.me/{me.username}?start={code}")
        elif sub == "users" or sub == "stats":
            users = await list_active_users(session)
            spend = {u.telegram_id: await month_spend(session, u.telegram_id)
                     for u in users}
            await message.answer(format_users(users, spend))
        elif sub == "revoke" and len(args) > 1 and args[1].isdigit():
            uid = int(args[1])
            await set_user_status(session, uid, "revoked")
            await set_user_token(session, uid, None)  # шифро-токен в БД не держим
            await session.commit()
            invalidate_user_broker(deps, uid)
            await message.answer(f"⛔️ {uid} отключён, его токен стёрт из БД.\n"
                                 f"Посоветуй ему также отозвать токен в Tinkoff.")
        elif sub == "set_budget" and len(args) > 2 and args[1].isdigit():
            try:
                budget = Decimal(args[2])
            except InvalidOperation:
                budget = None
            if budget is None or budget < 0:
                await message.answer("Сумма должна быть числом ≥ 0 (0 = блок). "
                                     + USAGE)
                return
            await set_user_budget(session, int(args[1]), budget)
            await session.commit()
            await message.answer(f"💰 Бюджет {args[1]} = ${budget}/мес.")
        else:
            await message.answer(USAGE)
