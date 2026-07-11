from datetime import datetime, timedelta, timezone
from decimal import Decimal

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.news.models import NewsItem
from roaring_kittens.scoring import TrackStats
from roaring_kittens.telegram.formatting import (
    format_analyst_report, format_portfolio, format_prev_call_note, format_track,
)


def _pos(ticker, qty, avg, cur, pnl):
    return Position(ticker=ticker, name=ticker, figi="X", quantity=Decimal(qty),
                    avg_price=Decimal(avg), current_price=Decimal(cur), pnl_pct=Decimal(pnl))


def test_format_portfolio_contains_positions_and_total():
    snap = PortfolioSnapshot(
        total_value=Decimal("1234567.89"),
        positions=[_pos("SBER", "500", "280", "294", "5.0"),
                   _pos("VTBR", "1000", "86.5", "79.2", "-8.4")],
    )
    text = format_portfolio(snap)
    assert "1 234 568" in text          # округление и разделители тысяч
    assert "SBER" in text and "+5.0%" in text
    assert "VTBR" in text and "−8.4%" in text


def test_format_empty_portfolio():
    text = format_portfolio(PortfolioSnapshot(total_value=Decimal("0"), positions=[]))
    assert "пуст" in text.lower()


def test_format_portfolio_movers_first_and_arrows():
    snap = PortfolioSnapshot(
        total_value=Decimal("1000000"),
        positions=[_pos("AAA", "1", "100", "90", "-10.0"),
                   _pos("BBB", "1", "100", "120", "20.0")],
    )
    text = format_portfolio(snap)
    # лидер BBB должен идти раньше аутсайдера AAA
    assert text.index("BBB") < text.index("AAA")
    assert "▲" in text and "▼" in text
    assert "Лидер" in text and "Аутсайдер" in text


def test_format_analyst_report():
    r = AnalystReport(ticker="SBER", stance="bullish",
                      summary="Выглядит сильно.", key_points=["Прибыль растёт"],
                      risks=["Перекупленность"], confidence=0.8)
    text = format_analyst_report(r)
    assert "SBER" in text and "🟢" in text          # bullish → зелёный
    assert "Прибыль растёт" in text and "Перекупленность" in text
    assert "80%" in text                              # confidence


def test_format_analyst_report_caps_confidence_on_low_data():
    r = AnalystReport(ticker="SBER", stance="bullish", summary="s",
                      key_points=["k"], risks=["r"], confidence=0.85)
    text = format_analyst_report(r, low_data=True)
    assert "85%" not in text
    assert "40%" in text and "мало данных" in text


def test_format_analyst_report_renders_clickable_sources():
    r = AnalystReport(ticker="SBER", stance="neutral", summary="s",
                      key_points=["k"], risks=["r"], confidence=0.5)
    src = [NewsItem(source="rbc", url="https://x/1", headline="Заголовок",
                    body=None, published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])]
    text = format_analyst_report(r, sources=src)
    assert '<a href="https://x/1">Заголовок</a>' in text
    assert "Источники" in text


_NOW = datetime.now(tz=timezone.utc)


def test_prev_call_note_same_stance():
    note = format_prev_call_note("neutral", 0.6, _NOW - timedelta(days=3), "neutral", _NOW)
    assert "3 дн" in note and "⚪️" in note and "изменилось" not in note


def test_prev_call_note_flags_stance_flip():
    note = format_prev_call_note("bullish", 0.7, _NOW - timedelta(days=2), "bearish", _NOW)
    assert "🟢" in note and "мнение изменилось" in note


def test_format_analyst_report_includes_prev_note():
    r = AnalystReport(ticker="SBER", stance="bullish", summary="s",
                      key_points=["k"], risks=["r"], confidence=0.7)
    text = format_analyst_report(r, prev_note="🕰 Прошлый разбор (сегодня): ⚪️ neutral 60%")
    assert "Прошлый разбор" in text


def test_format_track_shows_hitrate_baseline_and_misses():
    worst = [ScoredCall(ticker="SBER", stance="bullish",
                        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc), source="ask",
                        horizon_days=20, stock_return_pct=Decimal("-8.3"),
                        imoex_return_pct=Decimal("1.0"), verdict="miss")]
    stats = TrackStats(primary_horizon=20, total_scored=10,
                       by_stance={"bullish": (4, 7), "neutral": (2, 3)},
                       avg_excess_pp=Decimal("1.8"), imoex_up_windows=6,
                       worst=worst, per_horizon={5: (5, 8), 20: (6, 10)})
    text = format_track(stats, unscored=4)
    assert "4/7" in text and "+1.8" in text
    assert "60%" in text                     # бейзлайн: 6/10 окон IMOEX рос
    assert "SBER" in text and "−9.3" in text  # excess промаха (−8.3−1.0), знак честный
    assert "единой оценки: 4" in text


def test_format_track_empty():
    stats = TrackStats(primary_horizon=20, total_scored=0, by_stance={},
                       avg_excess_pp=Decimal("0"), imoex_up_windows=0)
    assert "пока нет" in format_track(stats, unscored=2).lower()


def test_format_track_shows_horizons_while_primary_matures():
    # 5-дневные оценки уже есть, 20-дневное окно ещё не дозрело — НЕ «пока нет»
    stats = TrackStats(primary_horizon=20, total_scored=0, by_stance={},
                       avg_excess_pp=Decimal("0"), imoex_up_windows=0,
                       per_horizon={5: (3, 4)})
    text = format_track(stats, unscored=1)
    assert "5д: 3/4" in text and "зреет" in text.lower()
    assert "пока нет" not in text.lower()
