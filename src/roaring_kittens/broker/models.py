from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    ticker: str
    name: str
    figi: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    pnl_pct: Decimal  # (current-avg)/avg * 100, округлено до 0.1


@dataclass(frozen=True)
class PortfolioSnapshot:
    total_value: Decimal
    positions: list[Position]


@dataclass(frozen=True)
class Candle:
    day: date
    open: Decimal
    close: Decimal
    high: Decimal
    low: Decimal
    volume: int
