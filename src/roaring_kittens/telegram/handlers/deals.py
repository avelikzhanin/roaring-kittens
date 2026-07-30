"""Сделки: список, принятие/отказ идеи, «продал», «держу дальше»."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from roaring_kittens.db.deals import (
    DealRecord, accept_deal, close_deal, decline_deal, expire_deal,
    expire_if_stale, get_deal, has_live_deal, list_deals, mute_deal,
)
from roaring_kittens.db.users import get_active_user
from roaring_kittens.deps import Deps

log = structlog.get_logger()
router = Router()

HOLD_MUTE_DAYS = 3


def _pct(entry: Decimal, now_price: Decimal) -> Decimal:
    return ((now_price - entry) / entry * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def format_deals(active: list[DealRecord], accepted: list[DealRecord],
                 closed: list[DealRecord], prices: dict[str, Decimal]) -> str:
    lines = ["💼 <b>Сделки</b>", ""]
    if active:
        lines.append("📈 <b>Открытые:</b>")
        for d in active:
            entry = d.entry_actual or d.entry_suggested
            now_price = prices.get(d.figi)
            pnl = f" · {'+' if _pct(entry, now_price) >= 0 else ''}{_pct(entry, now_price)}%" \
                if (now_price and entry) else ""
            lines.append(f"№{d.deal_no} {d.ticker} · вход {entry} ₽"
                         f"{f' → сейчас {now_price} ₽' if now_price else ''}{pnl}"
                         f" · цель {d.target_price} / выход {d.exit_price}")
        lines.append("")
    if accepted:  # принята, но покупки на счёте ещё не видно — без PnL
        lines.append("⏳ <b>Ждут покупки:</b>")
        for d in accepted:
            lines.append(f"№{d.deal_no} {d.ticker} · план входа ~{d.entry_suggested} ₽ "
                         f"· цель {d.target_price} / выход {d.exit_price}")
        lines.append("")
    if closed:
        lines.append("📕 <b>Закрытые:</b>")
        # итог — по ВСЕМ закрытым; показываем только последние 10
        total = sum((d.result_pct or Decimal("0")) for d in closed)
        for d in closed[-10:]:
            res = d.result_pct if d.result_pct is not None else Decimal("0")
            days = (d.closed_at - (d.opened_at or d.proposed_at)).days
            mark = "✅" if res >= 0 else "❌"
            lines.append(f"№{d.deal_no} {d.ticker} · "
                         f"{'+' if res >= 0 else ''}{res}% за {days} дн {mark}")
        lines += ["", f"Итог по всем закрытым ({len(closed)}): "
                      f"{'+' if total >= 0 else ''}{total}%"]
    if not active and not accepted and not closed:
        lines.append("Пока пусто. Идеи приходят сами, когда комитет находит "
                     "сделку; свои покупки я тоже подхвачу на утренней сверке.")
    return "\n".join(lines)


@router.message(Command("deals"))
@router.message(F.text == "💼 Сделки")
async def cmd_deals(message: Message, deps: Deps) -> None:
    if message.chat.type != "private":
        await message.answer("Сделки — только в личке со мной.")
        return
    async with deps.session_factory() as session:
        user = await get_active_user(session, message.from_user.id)
    if user is None:
        await message.answer("🔒 Сделки доступны подключённым пользователям "
                             "(нужен инвайт-код от владельца).")
        return
    async with deps.session_factory() as session:
        proposed = await list_deals(session, user.telegram_id,
                                    statuses=("proposed",))
        # lazy-expire протухших предложений прямо при рендере
        for d in proposed:
            await expire_if_stale(session, d.id, ttl_hours=48)
        await session.commit()
        proposed = await list_deals(session, user.telegram_id,
                                    statuses=("proposed",))
        active = await list_deals(session, user.telegram_id, statuses=("active",))
        accepted = await list_deals(session, user.telegram_id,
                                    statuses=("accepted",))
        closed = await list_deals(session, user.telegram_id, statuses=("closed",))
    prices: dict[str, Decimal] = {}
    if active:
        try:
            prices = await deps.broker.get_last_prices([d.figi for d in active])
        except Exception as exc:
            log.warning("deals_prices_failed", error=str(exc))
    await message.answer(format_deals(active, accepted, closed, prices))
    # идеи без ответа — отдельными карточками с живыми кнопками (после ночного
    # буфера, где клавиатура теряется, это единственный путь принять идею)
    from roaring_kittens.deals_service import idea_keyboard
    for d in proposed:
        await message.answer(
            f"💡 <b>Ждёт решения: идея №{d.deal_no} — купить {d.ticker} "
            f"по ~{d.entry_suggested} ₽</b>\n"
            f"🎯 Цель: {d.target_price} ₽ · 🛑 Продаём если: ниже {d.exit_price} ₽",
            reply_markup=idea_keyboard(d.id))


async def _owned_deal(callback: CallbackQuery, deps: Deps) -> DealRecord | None:
    try:
        deal_id = UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return None
    async with deps.session_factory() as session:
        deal = await get_deal(session, deal_id)
    if deal is None or deal.user_id != callback.from_user.id:
        await callback.answer("Это не твоя сделка", show_alert=True)
        return None
    return deal


async def _drop_keyboard(callback: CallbackQuery) -> None:
    """Кнопки с обработанной идеи снимаем — старые сообщения не должны стрелять."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass  # сообщение могло быть из буфера/старое — не критично


@router.callback_query(F.data.startswith("deal_take:"))
async def cb_take(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    async with deps.session_factory() as session:
        if await expire_if_stale(session, deal.id, ttl_hours=48):
            await session.commit()
            await _drop_keyboard(callback)
            await callback.answer("Идея устарела (48ч) — жди следующую",
                                  show_alert=True)
            return
        # дубль покрытия: по тикеру уже есть живая сделка (напр., converted
        # после самостоятельной покупки) — идею гасим, вторую не открываем
        if await has_live_deal(session, deal.user_id, deal.ticker):
            await expire_deal(session, deal.id)
            await session.commit()
            await _drop_keyboard(callback)
            await callback.answer("Эта бумага уже под сопровождением — /deals",
                                  show_alert=True)
            return
        taken = await accept_deal(session, deal.id)  # WHERE status='proposed'
        await session.commit()
    if not taken:
        await callback.answer("Уже обработана")
        return
    await _drop_keyboard(callback)
    await callback.answer("Записал!")
    await callback.message.answer(
        f"📝 Сделка №{deal.deal_no} {deal.ticker} принята.\n"
        f"Купи в приложении Т-Инвестиций — я увижу покупку на счёте при "
        f"ближайшей сверке и начну следить за целью {deal.target_price} ₽ "
        f"и выходом {deal.exit_price} ₽.")


@router.callback_query(F.data.startswith("deal_skip:"))
async def cb_skip(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    async with deps.session_factory() as session:
        declined = await decline_deal(session, deal.id)  # WHERE status='proposed'
        await session.commit()
    if not declined:  # тап по старой кнопке уже активной сделки — НЕ убиваем её
        await callback.answer("Уже обработана")
        return
    await _drop_keyboard(callback)
    await callback.answer("Ок, пропускаем — неделю по этой бумаге не предлагаю")


@router.callback_query(F.data.startswith("deal_sold:"))
async def cb_sold(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    if deal.status != "active":
        await callback.answer("Сделка уже закрыта")
        return
    price = None
    try:
        prices = await deps.broker.get_last_prices([deal.figi])
        price = prices.get(deal.figi)
    except Exception as exc:
        log.warning("deal_close_price_failed", error=str(exc))
    entry = deal.entry_actual or deal.entry_suggested
    result = _pct(entry, price) if (price and entry) else None
    async with deps.session_factory() as session:
        await close_deal(session, deal.id, exit_actual=price,
                         close_reason="продал (кнопка)", result_pct=result)
        await session.commit()
    await callback.answer()
    await _drop_keyboard(callback)
    res_txt = f" Результат: {'+' if result >= 0 else ''}{result}%." if result is not None else ""
    await callback.message.answer(
        f"📕 Сделка №{deal.deal_no} {deal.ticker} закрыта.{res_txt} /deals — все.")


@router.callback_query(F.data.startswith("deal_hold:"))
async def cb_hold(callback: CallbackQuery, deps: Deps) -> None:
    deal = await _owned_deal(callback, deps)
    if deal is None:
        return
    until = datetime.now(tz=timezone.utc) + timedelta(days=HOLD_MUTE_DAYS)
    async with deps.session_factory() as session:
        await mute_deal(session, deal.id, until=until)
        await session.commit()
    await callback.answer(f"Ок, молчу про №{deal.deal_no} {HOLD_MUTE_DAYS} дня")
