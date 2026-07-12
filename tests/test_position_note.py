from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.broker.position_note import (
    position_note_from_snapshot, position_weight_pct,
)

SNAP = PortfolioSnapshot(
    total_value=Decimal("1000000"),
    positions=[Position(ticker="SBER", name="Сбер", figi="F", quantity=Decimal("500"),
                        avg_price=Decimal("280"), current_price=Decimal("294"),
                        pnl_pct=Decimal("5.0"))],
)
EMPTY = PortfolioSnapshot(total_value=Decimal("0"), positions=[])


def test_note_for_held_position_has_qty_and_weight():
    note = position_note_from_snapshot(SNAP, "SBER")
    assert "500 шт по 280" in note and "14.7%" in note  # 500*294/1e6*100


def test_note_for_missing_position():
    assert "НЕТ" in position_note_from_snapshot(SNAP, "GAZP")


def test_weight_pct():
    assert position_weight_pct(SNAP, "SBER") == Decimal("14.7")
    assert position_weight_pct(SNAP, "GAZP") is None
    assert position_weight_pct(EMPTY, "SBER") is None  # пустой счёт — не делим на 0
