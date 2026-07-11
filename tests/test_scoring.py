from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.scoring import build_track_stats, evaluate_call

D = Decimal


def test_bullish_needs_growth_and_beating_index():
    assert evaluate_call("bullish", D("5"), D("2")) == "hit"
    assert evaluate_call("bullish", D("2"), D("5")) == "miss"   # вырос, но хуже IMOEX
    assert evaluate_call("bullish", D("-1"), D("-3")) == "miss"  # обогнал, но упал


def test_bearish_symmetric():
    assert evaluate_call("bearish", D("-4"), D("-1")) == "hit"
    assert evaluate_call("bearish", D("1"), D("2")) == "miss"


def test_neutral_band():
    assert evaluate_call("neutral", D("2"), D("0")) == "hit"    # |excess|=2 <= 3
    assert evaluate_call("neutral", D("6"), D("1")) == "miss"   # |excess|=5 > 3


def _sc(stance, verdict, excess, horizon=20, ticker="SBER"):
    return ScoredCall(ticker=ticker, stance=stance,
                      created_at=datetime.now(tz=timezone.utc), source="ask",
                      horizon_days=horizon, stock_return_pct=D(excess) + D("1"),
                      imoex_return_pct=D("1"), verdict=verdict)


def test_build_track_stats_aggregates_and_ranks_worst():
    rows = [_sc("bullish", "hit", "4"), _sc("bullish", "miss", "-9"),
            _sc("bearish", "hit", "-15", ticker="LKOH"),   # большой |excess|, но ХИТ — не промах
            _sc("neutral", "miss", "10", ticker="GAZP"),   # промах с ПОЛОЖИТЕЛЬНЫМ excess
            _sc("bearish", "miss", "-2", ticker="VTBR"),
            _sc("bullish", "hit", "3", horizon=5)]  # другой горизонт — не в основной срез
    stats = build_track_stats(rows, primary_horizon=20)
    assert stats.total_scored == 5
    assert stats.by_stance["bullish"] == (1, 2)
    # худшие = ТОЛЬКО промахи, по |excess| убыв.; bearish-хит с -15 не вытесняет
    assert [w.excess_pp for w in stats.worst] == [D("10"), D("-9"), D("-2")]
    assert stats.imoex_up_windows == 5  # imoex_return=1 > 0 во всех 5
