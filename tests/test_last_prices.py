from decimal import Decimal
from types import SimpleNamespace

from tinkoff.invest import Quotation

from roaring_kittens.broker.tinkoff_client import map_last_prices


def test_map_last_prices():
    resp = SimpleNamespace(last_prices=[
        SimpleNamespace(figi="F1", price=Quotation(units=283, nano=900000000)),
        SimpleNamespace(figi="F2", price=Quotation(units=60, nano=875000000)),
    ])
    prices = map_last_prices(resp)
    assert prices == {"F1": Decimal("283.9"), "F2": Decimal("60.875")}
