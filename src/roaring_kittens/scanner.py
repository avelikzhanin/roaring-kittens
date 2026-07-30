"""Сканер голубых фишек: дешёвый скрининг (mini) -> комитет по лучшему -> идеи.

Кост системный (вне use_user): скрининг ~$0.001/бумага, комитет <=1/день.
Guards (из ревью плана): исключение кандидатов по council_runs (видит и
вето-прогоны) с окном 7 дней в тон per-user guard'у идей; пропуск неторговых
дней; перезагрузка universe при пустых весах IMOEX."""
from datetime import date, datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.broker.tech import compute_indicators
from roaring_kittens.committee.context import CANDLES_DAYS
from roaring_kittens.db.council import council_run_recently
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.users import list_active_users
from roaring_kittens.deals_service import propose_deal_from_council
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.news.sources import CROWD_SOURCES
from roaring_kittens.users_service import get_user_broker

log = structlog.get_logger()

SCAN_TOP_N = 10
SCORE_THRESHOLD = 70
SCREEN_MODEL = "gpt-4o-mini"
SCAN_EXCLUDE_HOURS = 24 * 7  # окно = 7-дневному guard'у идей (ревью: не 24ч)

SCREEN_SYSTEM = """Ты — скринер акций Мосбиржи. По технике и свежим заголовкам оцени,
интересна ли бумага К ПОКУПКЕ ПРЯМО СЕЙЧАС для консервативного частного инвестора.
score 0-100 (70+ = стоит полного разбора комитетом). Не выдумывай фактов.
Обзорные/пустые дни — низкий score. По-русски, кратко."""


class ScreenVerdict(BaseModel):
    attractive: bool
    score: int = Field(ge=0, le=100)
    reason_short: str = Field(description="одна фраза почему")


def pick_best(scored: list[tuple[str, ScreenVerdict]]):
    """(ticker, verdict) с максимальным score >= порога, только attractive."""
    good = [(t, v) for t, v in scored if v.attractive and v.score >= SCORE_THRESHOLD]
    if not good:
        return None
    return max(good, key=lambda x: x[1].score)


async def _is_trading_day(deps, instrument) -> bool:
    """Последняя дневная свеча датирована сегодня? Праздники Мосбиржи — нет."""
    try:
        candles = await deps.broker.get_daily_candles(instrument.figi, days=10)
    except Exception as exc:
        log.warning("scanner_trading_day_check_failed", error=str(exc))
        return False
    if not candles:
        return False
    last = max(c.day for c in candles)
    return last >= datetime.now(tz=timezone.utc).date()


async def _screen_one(deps, instrument) -> ScreenVerdict | None:
    try:
        # 90 дней: MA50 требует >=50 ТОРГОВЫХ свечей (ревью: 60 календарных мало)
        candles = await deps.broker.get_daily_candles(instrument.figi,
                                                      days=CANDLES_DAYS)
        ind = compute_indicators(candles)
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [instrument.ticker],
                                              since=since)
        news = [n for n in news if n.source not in CROWD_SOURCES]
        headlines = "\n".join(f"- {n.headline}" for n in news[:5]) or "(нет свежих)"
        user = (f"Тикер: {instrument.ticker} ({instrument.name})\n"
                f"Техника: RSI14={ind.rsi14}, MA20={ind.ma20}, MA50={ind.ma50}, "
                f"объём/среднему={ind.volume_ratio}\n"
                f"Заголовки за 24ч:\n{headlines}")
        return await deps.llm.parse(
            model=SCREEN_MODEL, operation="scanner_screen",
            messages=[{"role": "system", "content": SCREEN_SYSTEM},
                      {"role": "user", "content": user}],
            schema=ScreenVerdict)
    except Exception as exc:
        log.warning("scanner_screen_failed", ticker=instrument.ticker,
                    error=str(exc))
        return None


async def scanner_job(deps, bot) -> None:
    """Пн-пт 10:40 МСК: скрининг топ-10 IMOEX -> комитет по лучшему -> идеи юзерам."""
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    top = deps.universe.top_by_weight(SCAN_TOP_N)
    if not top:
        # рестарт при лежащем ISS оставил universe без весов — пробуем перегрузить
        log.warning("scanner_no_weights_reloading_universe")
        try:
            await deps.universe.load()
        except Exception as exc:
            log.error("scanner_universe_reload_failed", error=str(exc))
            return
        top = deps.universe.top_by_weight(SCAN_TOP_N)
        if not top:
            log.error("scanner_no_weights")
            return
    if not await _is_trading_day(deps, top[0]):
        log.info("scanner_skipped_non_trading_day")
        return
    candidates = []
    for instrument in top:
        async with deps.session_factory() as session:
            # council_runs видит И вето-прогоны (calls — нет): без этого сканер
            # пересобирал бы комитет по отклоняемому тикеру каждый день
            if await council_run_recently(session, instrument.ticker,
                                          hours=SCAN_EXCLUDE_HOURS):
                continue
        candidates.append(instrument)
    if not candidates:
        log.info("scanner_no_candidates")
        return
    scored = []
    for instrument in candidates:
        verdict = await _screen_one(deps, instrument)
        if verdict is not None:
            scored.append((instrument.ticker, verdict))
    best = pick_best(scored)
    log.info("scanner_screened", total=len(scored),
             best=best[0] if best else None,
             best_score=best[1].score if best else None,
             best_reason=best[1].reason_short if best else None)
    if best is None:
        return
    instrument = deps.universe.get(best[0])
    try:  # комитет без позиционного контекста (broker=None): рыночный скан
        from roaring_kittens.committee.runner import run_council_flow
        outcome = await run_council_flow(deps, instrument, owner_id, broker=None)
    except Exception as exc:
        log.error("scanner_council_failed", ticker=best[0], error=str(exc))
        return
    if not outcome.risk.approved or outcome.proposal.action != "buy":
        log.info("scanner_council_no_buy", ticker=best[0],
                 action=outcome.proposal.action)
        return
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    for u in users:  # идея каждому подключённому; per-user guards внутри propose
        try:
            broker = await get_user_broker(deps, u.telegram_id)
            if broker is None:
                continue
            await propose_deal_from_council(deps, bot, u.telegram_id,
                                            instrument, outcome,
                                            source="scanner")
        except Exception as exc:
            log.error("scanner_propose_failed", user=u.telegram_id,
                      error=str(exc))
