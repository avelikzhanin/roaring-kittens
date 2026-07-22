"""Ежедневная сверка портфелей ВСЕХ юзеров с их тезисами: закрытия и новые позиции."""
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from roaring_kittens.ai.usage_context import use_budget_mode, use_user
from roaring_kittens.broker.benchmark import return_between
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.broker.position_note import position_weight_pct
from roaring_kittens.budget import budget_state
from roaring_kittens.committee.context import build_council_context
from roaring_kittens.committee.thesis_gen import run_thesis_draft
from roaring_kittens.db.theses import (
    ThesisRecord, close_thesis, get_active_theses, get_recently_deleted_tickers,
    save_thesis, set_thesis_backed,
)
from roaring_kittens.db.users import list_active_users
from roaring_kittens.telegram.formatting import esc
from roaring_kittens.universe.universe import Instrument
from roaring_kittens.users_service import get_cached_portfolio, get_user_broker

log = structlog.get_logger()

MIN_THESIS_WEIGHT_PP = Decimal("5")


@dataclass(frozen=True)
class SyncActions:
    to_close: list[ThesisRecord]   # ПОДКРЕПЛЁННЫЙ тезис, позиции больше нет
    to_draft: list[Position]       # позиция ≥ порога без активного тезиса (и не подавлена)
    to_back: list[ThesisRecord]    # тезис-«идея», бумага теперь реально куплена


def diff_positions(snap: PortfolioSnapshot, active: list[ThesisRecord],
                   suppressed: set[str],
                   min_weight_pct: Decimal = MIN_THESIS_WEIGHT_PP) -> SyncActions:
    held = {p.ticker for p in snap.positions}
    with_thesis = {t.ticker for t in active}
    # закрываем ТОЛЬКО подкреплённые тезисы: идея по некупленной бумаге — не «продажа»
    to_close = [t for t in active if t.backed_by_position and t.ticker not in held]
    to_back = [t for t in active if not t.backed_by_position and t.ticker in held]
    to_draft = [p for p in snap.positions
                if p.ticker not in with_thesis
                and p.ticker not in suppressed
                and (position_weight_pct(snap, p.ticker) or Decimal("0")) >= min_weight_pct]
    return SyncActions(to_close=to_close, to_draft=to_draft, to_back=to_back)


async def _realized_return(deps, thesis: ThesisRecord) -> Decimal | None:
    try:
        lookback = (datetime.now(tz=timezone.utc) - thesis.opened_at).days + 15
        candles = await deps.broker.get_daily_candles(thesis.figi, days=max(lookback, 40))
    except Exception as exc:
        log.warning("sync_candles_failed", ticker=thesis.ticker, error=str(exc))
        return None
    closes = sorted((c.day, c.close) for c in candles)
    start = thesis.opened_at.date()
    end = datetime.now(tz=timezone.utc).date()
    return return_between(closes, start, end)


async def sync_positions(deps, bot) -> None:
    """Цикл по активным юзерам с брокером; ошибка одного не роняет остальных."""
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    for u in users:
        broker = await get_user_broker(deps, u.telegram_id)
        if broker is None:
            continue
        started = time.monotonic()
        try:
            with use_user(u.telegram_id):
                await _sync_user(deps, bot, u.telegram_id, broker)
        except Exception as exc:
            log.error("sync_user_failed", user=u.telegram_id, error=str(exc))
        log.info("sync_user_done", user=u.telegram_id,
                 sec=round(time.monotonic() - started, 1))


async def _sync_user(deps, bot, owner_id: int, broker) -> None:
    # Кэш-портфель: снимок 8:50 переиспользуется дайджестом в 9:00 (один запрос)
    snap = await get_cached_portfolio(deps, owner_id, broker)
    if snap is None:
        log.error("sync_portfolio_failed", user=owner_id)
        return
    async with deps.session_factory() as session:
        active = await get_active_theses(session, owner_id=owner_id)
        suppressed = await get_recently_deleted_tickers(session, days=30,
                                                        owner_id=owner_id)
    actions = diff_positions(snap, active, suppressed=suppressed)
    # Бюджет: blocked — авто-тезисы (LLM) не генерим; econom — драфты на mini
    state, _, _ = await budget_state(deps, owner_id)
    if state == "blocked" and actions.to_draft:
        log.info("thesis_drafts_skipped_budget", user=owner_id,
                 skipped=len(actions.to_draft))
        actions = SyncActions(to_close=actions.to_close, to_draft=[],
                              to_back=actions.to_back)

    for thesis in actions.to_back:  # идея подтвердилась покупкой
        async with deps.session_factory() as session:
            await set_thesis_backed(session, thesis.id)
            await session.commit()

    for thesis in actions.to_close:
        ret = await _realized_return(deps, thesis)
        async with deps.session_factory() as session:
            await close_thesis(session, thesis.id, status="closed",
                               realized_return_pct=ret,
                               close_reason="позиция закрыта")
            await session.commit()
        sign = "" if ret is None else (f", результат {'+' if ret >= 0 else '−'}{abs(ret)}%"
                                       " за время тезиса")
        await bot.send_message(owner_id,
                               f"📕 Позиция {thesis.ticker} закрыта — тезис закрыт{sign}.\n"
                               f"Тезис был: {esc(thesis.thesis)}")

    for pos in actions.to_draft:
        instrument = deps.universe.get(pos.ticker) or Instrument(
            ticker=pos.ticker, figi=pos.figi, name=pos.name, aliases=frozenset())
        try:
            ctx = await build_council_context(deps, instrument, owner_id,
                                              today=datetime.now(tz=timezone.utc).date(),
                                              include_memory=False, broker=broker)
            with use_budget_mode("econom" if state == "econom" else "ok"):
                draft = await run_thesis_draft(deps.llm, ctx)
        except Exception as exc:
            log.error("thesis_draft_failed", ticker=pos.ticker, error=str(exc))
            continue
        async with deps.session_factory() as session:
            rec = await save_thesis(session, ticker=pos.ticker, figi=pos.figi,
                                    thesis=draft.thesis, invalidation=draft.invalidation,
                                    source="auto", confidence=draft.confidence,
                                    entry_price=pos.avg_price, backed_by_position=True,
                                    owner_id=owner_id)
            await session.commit()
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="🗑 Удалить тезис", callback_data=f"thesis_del:{rec.id}")]])
        await bot.send_message(
            owner_id,
            f"📌 Обнаружена позиция <b>{pos.ticker}</b> (вес ≥5%) без тезиса.\n"
            f"Сгенерировал тезис: {esc(draft.thesis)}\n"
            f"🚨 Инвалидация: {esc(draft.invalidation)}\n"
            f"Буду проверять его каждой новостью. Не согласен — удали.",
            reply_markup=kb)
    log.info("positions_synced", closed=len(actions.to_close),
             drafted=len(actions.to_draft), backed=len(actions.to_back))
