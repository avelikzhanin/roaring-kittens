"""Pure-функции о позиции пользователя. IO (get_portfolio) остаётся у вызывающего."""
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import PortfolioSnapshot


def position_weight_pct(snap: PortfolioSnapshot, ticker: str) -> Decimal | None:
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None or not snap.total_value:
        return None
    return (pos.quantity * pos.current_price / snap.total_value * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP)


def position_note_from_snapshot(snap: PortfolioSnapshot, ticker: str) -> str:
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None:
        return "Позиция: у пользователя НЕТ этой бумаги в портфеле."
    weight = position_weight_pct(snap, ticker) or Decimal("0")
    return (f"Позиция: {pos.quantity} шт по {pos.avg_price} ₽ "
            f"(P&L {pos.pnl_pct:+}%), вес {weight}% портфеля.")
