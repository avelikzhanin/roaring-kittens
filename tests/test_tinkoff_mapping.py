from decimal import Decimal
from types import SimpleNamespace

from tinkoff.invest import MoneyValue, Quotation

from roaring_kittens.broker.tinkoff_client import map_portfolio


def _money(units, nano=0):
    return MoneyValue(currency="rub", units=units, nano=nano)


def test_map_portfolio_filters_shares_and_computes_pnl():
    raw = SimpleNamespace(
        total_amount_portfolio=_money(1_000_000),
        positions=[
            SimpleNamespace(
                figi="BBG004730N88", instrument_type="share",
                quantity=Quotation(units=500, nano=0),
                average_position_price=_money(280),
                current_price=_money(294),
            ),
            SimpleNamespace(  # валюта — должна отфильтроваться
                figi="RUB000UTSTOM", instrument_type="currency",
                quantity=Quotation(units=1000, nano=0),
                average_position_price=_money(1),
                current_price=_money(1),
            ),
        ],
    )
    figi_map = {"BBG004730N88": ("SBER", "Сбер Банк")}
    snap = map_portfolio(raw, figi_map)
    assert snap.total_value == Decimal("1000000")
    assert len(snap.positions) == 1
    p = snap.positions[0]
    assert p.ticker == "SBER" and p.quantity == Decimal("500")
    assert p.pnl_pct == Decimal("5.0")  # (294-280)/280*100
