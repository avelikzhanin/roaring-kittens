"""Дневной прайс-алерт: |движение от вчерашнего закрытия| >= 5% — раз в день на тикер."""
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog

from roaring_kittens.alerts import send_alert
from roaring_kittens.db.theses import get_active_theses
from roaring_kittens.db.users import list_active_users
from roaring_kittens.db.watchlist import list_watchlist
from roaring_kittens.telegram.formatting import esc
from roaring_kittens.users_service import get_cached_portfolio, get_user_broker

log = structlog.get_logger()

DAY_MOVE_THRESHOLD_PP = Decimal("5")


def significant_move(prev_close: Decimal, last: Decimal) -> Decimal | None:
    if not prev_close:
        return None
    move = ((last - prev_close) / prev_close * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)
    return move if abs(move) >= DAY_MOVE_THRESHOLD_PP else None


class DayMoveDeduper:
    """Один алерт на (юзер, тикер) в день (in-memory, сброс при рестарте допустим).

    seen/mark разделены: помечаем ПОСЛЕ успешной отправки, чтобы сбой Telegram
    не глушил тикер на весь день. purge не даёт множеству расти вечно."""

    def __init__(self):
        self._seen: set[tuple[date, int, str]] = set()

    def seen(self, user_id: int, ticker: str, today: date) -> bool:
        return (today, user_id, ticker) in self._seen

    def mark(self, user_id: int, ticker: str, today: date) -> None:
        self._seen.add((today, user_id, ticker))

    def purge(self, today: date) -> None:
        self._seen = {k for k in self._seen if k[0] == today}


class DealSignalDeduper:
    """1 сигнал на (сделка, тип) в день; mark ПОСЛЕ успешной отправки."""

    def __init__(self):
        self._seen: set[tuple[date, str, str]] = set()

    def seen(self, deal_id: str, kind: str, today: date) -> bool:
        return (today, deal_id, kind) in self._seen

    def mark(self, deal_id: str, kind: str, today: date) -> None:
        self._seen.add((today, deal_id, kind))

    def purge(self, today: date) -> None:
        self._seen = {k for k in self._seen if k[0] == today}


_deduper = DayMoveDeduper()
_deal_deduper = DealSignalDeduper()
_prev_close_cache: dict[tuple[date, str], Decimal] = {}


def _purge_stale_cache(today: date) -> None:
    """Кэши ключуются днём — прошлые дни выкидываем (иначе вечный рост памяти)."""
    stale = [k for k in _prev_close_cache if k[0] != today]
    for k in stale:
        del _prev_close_cache[k]
    _deduper.purge(today)
    _deal_deduper.purge(today)


async def _prev_close(deps, figi: str, today: date) -> Decimal | None:
    key = (today, figi)
    if key not in _prev_close_cache:
        try:
            candles = await deps.broker.get_daily_candles(figi, days=10)
        except Exception as exc:
            log.warning("price_watch_candles_failed", figi=figi, error=str(exc))
            return None
        done = sorted(candles, key=lambda c: c.day)
        if not done:
            return None
        _prev_close_cache[key] = done[-1].close  # последняя ЗАВЕРШЁННАЯ сессия
    return _prev_close_cache[key]


async def _collect_interests(deps) -> dict[int, dict[str, str]]:
    """user_id -> {ticker: figi}: его портфель ∪ его watchlist ∪ его тезисы."""
    async with deps.session_factory() as session:
        users = await list_active_users(session)
        theses = await get_active_theses(session)
    interests: dict[int, dict[str, str]] = {}
    for u in users:
        figi_by_ticker: dict[str, str] = {}
        broker = await get_user_broker(deps, u.telegram_id)
        if broker is not None:
            snap = await get_cached_portfolio(deps, u.telegram_id, broker)
            if snap is not None:
                for p in snap.positions:
                    figi_by_ticker[p.ticker] = p.figi
        async with deps.session_factory() as session:
            watched = await list_watchlist(session, u.telegram_id)
        for t in watched:
            instr = deps.universe.get(t)
            if instr:
                figi_by_ticker.setdefault(t, instr.figi)
        for th in theses:
            if th.owner_id == u.telegram_id:
                figi_by_ticker.setdefault(th.ticker, th.figi)
        if figi_by_ticker:
            interests[u.telegram_id] = figi_by_ticker
    return interests


async def watch_deal_levels(deps, bot, today: date) -> None:
    """Проверка целей/выходов active-сделок по last prices. Без LLM.

    Один запрос по всем юзерам + один батч цен. Отдельный батч осознанно:
    сигналы сделок не должны зависеть от сбоев/пустоты interests-цикла."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from roaring_kittens.db.deals import list_all_active_deals
    from roaring_kittens.db.users import get_active_user
    async with deps.session_factory() as session:
        all_deals = await list_all_active_deals(session)
    if not all_deals:
        return
    # revoked после revoke: сделки остаются в БД, но сигналы им не шлём
    async with deps.session_factory() as session:
        alive = {d.user_id for d in all_deals
                 if await get_active_user(session, d.user_id) is not None}
    all_deals = [d for d in all_deals if d.user_id in alive]
    if not all_deals:
        return
    try:
        prices = await deps.broker.get_last_prices(
            list({d.figi for d in all_deals}))
    except Exception as exc:
        log.error("deal_levels_prices_failed", error=str(exc))
        return
    now = datetime.now(tz=timezone.utc)
    for d in all_deals:
        price = prices.get(d.figi)
        if price is None:
            continue
        if d.signal_muted_until and d.signal_muted_until > now:
            continue
        kind = None
        if price <= d.exit_price:
            kind = "exit"
        elif price >= d.target_price:
            kind = "target"
        if kind is None or _deal_deduper.seen(str(d.id), kind, today):
            continue
        entry = d.entry_actual or d.entry_suggested
        pnl = ""
        if entry:
            p = ((price - entry) / entry * 100).quantize(Decimal("0.1"))
            pnl = f" Сейчас: {'+' if p >= 0 else ''}{p}%."
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Продал", callback_data=f"deal_sold:{d.id}"),
            InlineKeyboardButton(text="Держу дальше",
                                 callback_data=f"deal_hold:{d.id}"),
        ]])
        text = (f"🛑 Сделка №{d.deal_no} {d.ticker}: цена {price} ₽ — сработал "
                f"сигнал выхода (ниже {d.exit_price} ₽). Рекомендую продать.{pnl}"
                if kind == "exit" else
                f"🎯 Сделка №{d.deal_no} {d.ticker}: цена {price} ₽ достигла цели "
                f"{d.target_price} ₽. Можно фиксировать прибыль.{pnl}")
        try:
            await send_alert(deps, bot, d.user_id, text,
                             critical=(kind == "exit"), keyboard=kb)
            _deal_deduper.mark(str(d.id), kind, today)
        except Exception as exc:
            log.error("deal_signal_failed", deal=str(d.id), error=str(exc))


async def price_watch_job(deps, bot) -> None:
    today = datetime.now(tz=timezone.utc).date()
    _purge_stale_cache(today)
    try:  # сигналы сделок — ядро Фазы 5: независимы от interests-цикла ниже
        await watch_deal_levels(deps, bot, today)
    except Exception as exc:
        log.error("watch_deal_levels_failed", error=str(exc))
    interests = await _collect_interests(deps)
    if not interests:
        return
    all_figi = {figi for m in interests.values() for figi in m.values()}
    try:  # last_prices — одним батчем по объединению (системный брокер)
        prices = await deps.broker.get_last_prices(list(all_figi))
    except Exception as exc:
        log.error("price_watch_last_prices_failed", error=str(exc))
        return
    for user_id, figi_by_ticker in interests.items():
        for ticker, figi in figi_by_ticker.items():
            last = prices.get(figi)
            if last is None:
                continue
            prev = await _prev_close(deps, figi, today)
            if prev is None:
                continue
            move = significant_move(prev, last)
            if move is None or _deduper.seen(user_id, ticker, today):
                continue
            arrow = "📈" if move > 0 else "📉"
            try:  # 403 одного юзера (заблокировал бота) не роняет цикл остальным
                await send_alert(
                    deps, bot, user_id,
                    f"{arrow} <b>{ticker}</b> {'+' if move > 0 else '−'}{abs(move)}% "
                    f"за день ({esc(str(prev))} → {esc(str(last))} ₽). "
                    f"Разбор: /council {ticker}")
                _deduper.mark(user_id, ticker, today)  # после отправки: сбой не глушит
            except Exception as exc:
                log.error("price_alert_failed", user=user_id, ticker=ticker,
                          error=str(exc))
    log.info("price_watch_done", users=len(interests), figis=len(all_figi))
