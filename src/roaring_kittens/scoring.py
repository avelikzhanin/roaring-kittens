from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog

from roaring_kittens.broker.benchmark import fetch_imoex_closes, return_between
from roaring_kittens.db.calls import ScoredCall, get_unscored_calls, save_score

log = structlog.get_logger()

NEUTRAL_BAND_PP = Decimal("3")
HORIZONS = (5, 20, 60)
PRIMARY_HORIZON = 20


def evaluate_call(stance: str, stock_return_pct: Decimal,
                  imoex_return_pct: Decimal) -> str:
    """Вердикт относительно бенчмарка: рост при отставании от IMOEX — не победа."""
    excess = stock_return_pct - imoex_return_pct
    if stance == "bullish":
        return "hit" if stock_return_pct > 0 and excess > 0 else "miss"
    if stance == "bearish":
        return "hit" if stock_return_pct < 0 and excess < 0 else "miss"
    return "hit" if abs(excess) <= NEUTRAL_BAND_PP else "miss"


@dataclass
class TrackStats:
    primary_horizon: int
    total_scored: int
    by_stance: dict[str, tuple[int, int]]   # stance -> (hits, total)
    avg_excess_pp: Decimal
    imoex_up_windows: int                   # окон с ростом IMOEX (для бейзлайна)
    worst: list[ScoredCall] = field(default_factory=list)
    per_horizon: dict[int, tuple[int, int]] = field(default_factory=dict)


def build_track_stats(rows: list[ScoredCall], primary_horizon: int = PRIMARY_HORIZON,
                      worst_n: int = 3) -> TrackStats:
    per_horizon: dict[int, tuple[int, int]] = {}
    for r in rows:
        h, t = per_horizon.get(r.horizon_days, (0, 0))
        per_horizon[r.horizon_days] = (h + (r.verdict == "hit"), t + 1)

    primary = [r for r in rows if r.horizon_days == primary_horizon]
    by_stance: dict[str, tuple[int, int]] = {}
    for r in primary:
        h, t = by_stance.get(r.stance, (0, 0))
        by_stance[r.stance] = (h + (r.verdict == "hit"), t + 1)

    avg = (sum(r.excess_pp for r in primary) / len(primary)).quantize(Decimal("0.1")) \
        if primary else Decimal("0")
    # Сначала фильтруем промахи, потом ранжируем по |excess| (= величина ошибки,
    # корректна для любого stance: bearish-промах имеет ПОЛОЖИТЕЛЬНЫЙ excess).
    misses = [r for r in primary if r.verdict == "miss"]
    worst = sorted(misses, key=lambda r: abs(r.excess_pp), reverse=True)[:worst_n]
    return TrackStats(primary_horizon=primary_horizon, total_scored=len(primary),
                      by_stance=by_stance, avg_excess_pp=avg,
                      imoex_up_windows=sum(1 for r in primary if r.imoex_return_pct > 0),
                      worst=worst, per_horizon=per_horizon)


async def score_due_calls(deps) -> int:
    """Оценивает все вызовы, дозревшие до горизонтов 5/20/60 дней. Возвращает счётчик."""
    now = datetime.now(tz=timezone.utc)
    frm = (now - timedelta(days=max(HORIZONS) + 120)).date()  # запас под retro-посев
    try:
        imoex = await fetch_imoex_closes(frm, now.date())
    except Exception as exc:
        log.error("scoring_imoex_unavailable", error=str(exc))
        return 0
    scored = 0
    for horizon in HORIZONS:
        async with deps.session_factory() as session:
            due = await get_unscored_calls(session, horizon, now)
        for call in due:
            lookback = (now - call.created_at).days + 15
            try:
                candles = await deps.broker.get_daily_candles(call.figi, days=lookback)
            except Exception as exc:
                log.warning("scoring_candles_failed", ticker=call.ticker, error=str(exc))
                continue
            closes = sorted((c.day, c.close) for c in candles)  # API-порядку не доверяем
            start = call.created_at.date()
            end = (call.created_at + timedelta(days=horizon)).date()
            stock_ret = return_between(closes, start, end)
            imoex_ret = return_between(imoex, start, end)
            if stock_ret is None or imoex_ret is None:
                continue
            verdict = evaluate_call(call.stance, stock_ret, imoex_ret)
            async with deps.session_factory() as session:
                await save_score(session, call.id, horizon, stock_ret, imoex_ret, verdict)
                await session.commit()
            scored += 1
    log.info("scoring_done", scored=scored)
    return scored
