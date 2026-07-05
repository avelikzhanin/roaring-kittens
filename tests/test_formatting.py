from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.news.models import NewsItem
from roaring_kittens.telegram.formatting import format_analyst_report, format_portfolio


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
