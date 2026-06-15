from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import PortfolioSnapshot


def _fmt_money(v: Decimal) -> str:
    return f"{v.quantize(Decimal('1'), ROUND_HALF_UP):,}".replace(",", " ")


def _fmt_pct(v: Decimal) -> str:
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v)}%"


def format_portfolio(snap: PortfolioSnapshot) -> str:
    if not snap.positions:
        return "📊 Портфель пуст."
    lines = [f"📊 <b>Портфель</b> — {_fmt_money(snap.total_value)} ₽", ""]
    for p in snap.positions:
        lines.append(
            f"<b>{p.ticker}</b> · {p.quantity} шт · "
            f"{p.avg_price} → {p.current_price} ₽ · {_fmt_pct(p.pnl_pct)}"
        )
    return "\n".join(lines)
