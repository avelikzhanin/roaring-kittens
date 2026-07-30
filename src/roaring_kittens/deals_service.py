"""Сделки: уровни, сайзинг-текст, предложение идей, активация/закрытие/конвертация."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from roaring_kittens.alerts import send_alert
from roaring_kittens.db.deals import (
    activate_deal, close_deal, create_proposal, expire_deal, has_live_deal,
    has_recent_proposal, list_deals,
)
from roaring_kittens.sizing import SizedSuggestion, suggest_qty
from roaring_kittens.telegram.formatting import esc
from roaring_kittens.users_service import get_cached_portfolio, get_user_broker

log = structlog.get_logger()

FALLBACK_EXIT_PCT = Decimal("0.07")    # −7%
FALLBACK_TARGET_PCT = Decimal("0.14")  # +14% (2R)
MIN_EXIT_GAP = Decimal("0.03")         # exit минимум на 3% ниже входа
MAX_EXIT_GAP = Decimal("0.20")         # и максимум на 20%
MIN_TARGET_GAP = Decimal("0.03")

ACCEPTED_TTL_DAYS = 7  # принял, но неделю не покупал -> идея снимается

# parse_mode=HTML: markdown-подчёркивания НЕ работают (паттерн — render.py)
DISCLAIMER = "<i>Не является индивидуальной инвестиционной рекомендацией.</i>"


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def sanitize_levels(*, entry: Decimal, target: float | None,
                    exit_price: float | None) -> tuple[Decimal, Decimal]:
    """(target, exit) с фолбэком на детерминированные уровни от входа."""
    fb_target = _q(entry * (1 + FALLBACK_TARGET_PCT))
    fb_exit = _q(entry * (1 - FALLBACK_EXIT_PCT))
    t = Decimal(str(target)) if target else None
    e = Decimal(str(exit_price)) if exit_price else None
    if e is None or not (entry * (1 - MAX_EXIT_GAP) <= e <= entry * (1 - MIN_EXIT_GAP)):
        e = fb_exit
    if t is None or t < entry * (1 + MIN_TARGET_GAP):
        t = fb_target
    return _q(t), _q(e)


def build_idea_text(*, deal_no: int, ticker: str, entry: Decimal,
                    target: Decimal, exit_price: Decimal, exit_note: str,
                    rationale: str, confidence: float,
                    sized: SizedSuggestion | None) -> str:
    up = _q((target - entry) / entry * 100)
    dn = _q((entry - exit_price) / entry * 100)
    lines = [
        f"💡 <b>Идея сделки №{deal_no} — купить {ticker} по ~{entry} ₽</b>", "",
        f"Почему: {esc(rationale)}",
        f"Комитет аналитиков: BUY, уверенность {round(confidence * 100)}%.", "",
        f"🎯 Цель: {target} ₽ (+{up}%)",
        f"🛑 Продаём если: цена ниже {exit_price} ₽ (−{dn}%) или {esc(exit_note)}",
    ]
    if sized is not None:
        lines += ["", f"📐 Размер: {sized.lots} лотов ({sized.qty} шт, ~{_q(sized.cost)} ₽)"]
        if sized.over_risk:
            lines.append(f"⚠️ Даже минимальный лот рискует {_q(sized.risk_rub)} ₽ — "
                         f"для твоего портфеля это выше нормы 1%.")
        else:
            lines.append(f"Логика: сработает выход — потеряешь ~{_q(sized.risk_rub)} ₽, "
                         f"это 1% портфеля, который я вижу.")
    lines += ["", "Решить можно и позже: /deals → «Ждут решения».", "", DISCLAIMER]
    return "\n".join(lines)


def idea_keyboard(deal_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Беру", callback_data=f"deal_take:{deal_id}"),
        InlineKeyboardButton(text="❌ Пропущу", callback_data=f"deal_skip:{deal_id}"),
    ]])


async def propose_deal_from_council(deps, bot, user_id: int, instrument,
                                    outcome) -> None:
    """Approved BUY -> идея сделки. Молчит, если: тикер уже в портфеле юзера,
    была сделка за 7 дней (включая «Пропущу»), уже есть живая сделка, нет цены
    входа. Ошибки глотает (идея — бонус, не ядро)."""
    try:
        proposal = outcome.proposal
        if not outcome.risk.approved or proposal.action != "buy":
            return
        broker = await get_user_broker(deps, user_id)
        if broker is None:
            return
        snap = await get_cached_portfolio(deps, user_id, broker)
        if snap is None:
            return
        if any(p.ticker == instrument.ticker for p in snap.positions):
            return  # докупки в v1 не предлагаем
        async with deps.session_factory() as session:
            if await has_recent_proposal(session, user_id, instrument.ticker, days=7):
                return
            if await has_live_deal(session, user_id, instrument.ticker):
                return  # бумага уже под сопровождением — дубль не плодим
        entry = outcome.state["ctx"].tech.last_close if outcome.state["ctx"].tech else None
        if entry is None:
            return
        target, exit_price = sanitize_levels(
            entry=entry, target=proposal.target_price,
            exit_price=proposal.exit_price)
        sized = suggest_qty(portfolio_value=snap.total_value, entry=entry,
                            exit_price=exit_price, lot=instrument.lot)
        async with deps.session_factory() as session:
            deal = await create_proposal(
                session, user_id=user_id, ticker=instrument.ticker,
                figi=instrument.figi, source="council",
                council_run_id=outcome.run_id, entry_suggested=entry,
                qty_suggested=Decimal(sized.qty) if sized else None,
                target_price=target, exit_price=exit_price,
                exit_note=proposal.invalidation)
            await session.commit()
        # send_alert: ночью идея буферизуется (кнопки утром живут в /deals —
        # «Ждут решения»), quiet hours не нарушаем. Сбой отправки -> expire
        # строки, чтобы 7-дневный guard не глушил идею, которую юзер НЕ видел.
        text = build_idea_text(deal_no=deal.deal_no, ticker=instrument.ticker,
                               entry=entry, target=target, exit_price=exit_price,
                               exit_note=proposal.invalidation,
                               rationale=proposal.thesis,
                               confidence=proposal.confidence, sized=sized)
        try:
            await send_alert(deps, bot, user_id, text,
                             keyboard=idea_keyboard(deal.id))
        except Exception:
            async with deps.session_factory() as session:
                await expire_deal(session, deal.id)
                await session.commit()
            raise
        log.info("deal_proposed", user=user_id, ticker=instrument.ticker,
                 deal_no=deal.deal_no)
    except Exception as exc:
        log.error("deal_propose_failed", user=user_id,
                  ticker=getattr(instrument, "ticker", "?"), error=str(exc))


async def sync_deals_for_user(deps, bot, user_id: int, snap) -> None:
    """Утренняя сверка сделок со счётом: активировать accepted, закрыть
    исчезнувшие active, конвертировать «ничейные» позиции.

    Инварианты (ревью плана): не больше ОДНОЙ активации на тикер (лишние
    accepted протухают); конвертация молчит, пока по тикеру есть ЛЮБАЯ живая
    сделка (proposed тоже — иначе покупка до тапа даёт двойное покрытие);
    per-item try — сбой одной сделки (403/timeout) не срывает остальные."""
    held = {p.ticker: p for p in snap.positions}
    async with deps.session_factory() as session:
        proposed = await list_deals(session, user_id, statuses=("proposed",))
        accepted = await list_deals(session, user_id, statuses=("accepted",))
        active = await list_deals(session, user_id, statuses=("active",))
    covered = ({d.ticker for d in proposed} | {d.ticker for d in accepted}
               | {d.ticker for d in active})
    active_tickers = {d.ticker for d in active}
    now = datetime.now(tz=timezone.utc)

    # accepted: свежие первыми — активируем самую свежую на тикер, прочие гасим
    activated_tickers: set[str] = set()
    for d in sorted(accepted, key=lambda x: x.proposed_at, reverse=True):
        try:
            if d.ticker in activated_tickers or d.ticker in active_tickers:
                async with deps.session_factory() as session:
                    await expire_deal(session, d.id)   # дубль на тикер
                    await session.commit()
                continue
            pos = held.get(d.ticker)
            if pos is None:
                if now - d.proposed_at > timedelta(days=ACCEPTED_TTL_DAYS):
                    async with deps.session_factory() as session:
                        await expire_deal(session, d.id)
                        await session.commit()
                    await bot.send_message(
                        user_id, f"🗑 Идея №{d.deal_no} {d.ticker} снята — "
                                 f"покупки за {ACCEPTED_TTL_DAYS} дней не увидел.")
                continue
            async with deps.session_factory() as session:
                await activate_deal(session, d.id, entry_actual=pos.avg_price,
                                    qty_actual=pos.quantity)
                await session.commit()
            activated_tickers.add(d.ticker)
            await bot.send_message(
                user_id,
                f"✅ Вижу покупку: {d.ticker} {pos.quantity} шт по "
                f"{pos.avg_price} ₽.\nСделка №{d.deal_no} открыта — слежу за "
                f"целью {d.target_price} ₽ и выходом {d.exit_price} ₽.")
        except Exception as exc:
            log.error("deal_activate_failed", user=user_id, deal=str(d.id),
                      error=str(exc))

    for d in active:  # позиция исчезла -> закрываем по last price
        try:
            if d.ticker in held:
                continue
            price = None
            try:
                prices = await deps.broker.get_last_prices([d.figi])
                price = prices.get(d.figi)
            except Exception as exc:
                log.warning("deal_autoclose_price_failed", error=str(exc))
            entry = d.entry_actual or d.entry_suggested
            result = None
            if price and entry:
                result = ((price - entry) / entry * 100).quantize(Decimal("0.1"))
            async with deps.session_factory() as session:
                await close_deal(session, d.id, exit_actual=price,
                                 close_reason="позиция закрыта на счёте",
                                 result_pct=result)
                await session.commit()
            res_txt = f" Результат: {'+' if result >= 0 else ''}{result}%." \
                if result is not None else ""
            await bot.send_message(
                user_id, f"📕 Вижу продажу {d.ticker} — сделка №{d.deal_no} "
                         f"закрыта.{res_txt} /deals — все.")
        except Exception as exc:
            log.error("deal_autoclose_failed", user=user_id, deal=str(d.id),
                      error=str(exc))

    for ticker, pos in held.items():  # «ничейная» позиция -> converted-сделка
        try:
            if ticker in covered or ticker in activated_tickers:
                continue
            target, exit_price = sanitize_levels(entry=pos.current_price,
                                                 target=None, exit_price=None)
            async with deps.session_factory() as session:
                deal = await create_proposal(
                    session, user_id=user_id, ticker=ticker, figi=pos.figi,
                    source="converted", council_run_id=None,
                    entry_suggested=pos.avg_price, qty_suggested=pos.quantity,
                    target_price=target, exit_price=exit_price,
                    exit_note="существенное ухудшение новостного фона",
                    status="proposed")
                await activate_deal(session, deal.id, entry_actual=pos.avg_price,
                                    qty_actual=pos.quantity)
                await session.commit()
            await bot.send_message(
                user_id,
                f"💼 Взял позицию {ticker} под сопровождение как сделку "
                f"№{deal.deal_no} (вход {pos.avg_price} ₽ со счёта).\n"
                f"🎯 Цель: {target} ₽ · 🛑 Продаём если: ниже {exit_price} ₽.\n"
                f"/deals — все сделки.")
        except Exception as exc:
            log.error("deal_convert_failed", user=user_id, ticker=ticker,
                      error=str(exc))
