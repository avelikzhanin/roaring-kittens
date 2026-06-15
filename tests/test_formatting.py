from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.telegram.formatting import format_portfolio


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
