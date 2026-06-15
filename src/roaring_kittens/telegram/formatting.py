from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot

STANCE_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪️"}


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


def format_analyst_report(r: AnalystReport) -> str:
    lines = [
        f"{STANCE_EMOJI[r.stance]} <b>{r.ticker}</b> — {r.stance} "
        f"(уверенность {round(r.confidence * 100)}%)",
        "",
        r.summary,
        "",
        "<b>Ключевое:</b>",
        *[f"• {p}" for p in r.key_points],
        "",
        "<b>Риски:</b>",
        *[f"⚠️ {p}" for p in r.risks],
        "",
        "<i>Это аналитический разбор, не инвестрекомендация.</i>",
    ]
    return "\n".join(lines)
