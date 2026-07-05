from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.news.models import NewsItem

STANCE_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪️"}

# Потолок показываемой уверенности, когда данных мало (нет техники или новостей).
LOW_DATA_CONFIDENCE_CAP = 40


def _fmt_money(v: Decimal) -> str:
    return f"{v.quantize(Decimal('1'), ROUND_HALF_UP):,}".replace(",", " ")


def _fmt_pct(v: Decimal) -> str:
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v)}%"


def format_portfolio(snap: PortfolioSnapshot) -> str:
    if not snap.positions:
        return "📊 Портфель пуст."
    # movers-first: сортируем по P&L (с момента входа) убыв., чтобы лидеры были сверху
    positions = sorted(snap.positions, key=lambda p: p.pnl_pct, reverse=True)
    lines = [f"📊 <b>Портфель</b> — {_fmt_money(snap.total_value)} ₽"]
    if len(positions) >= 2:
        best, worst = positions[0], positions[-1]
        lines.append(
            f"Лидер: <b>{best.ticker}</b> {_fmt_pct(best.pnl_pct)} · "
            f"Аутсайдер: <b>{worst.ticker}</b> {_fmt_pct(worst.pnl_pct)}"
        )
    lines.append("")
    for p in positions:
        arrow = "▲" if p.pnl_pct >= 0 else "▼"
        lines.append(
            f"{arrow} <b>{p.ticker}</b> · {p.quantity} шт · "
            f"{p.avg_price} → {p.current_price} ₽ · {_fmt_pct(p.pnl_pct)}"
        )
    return "\n".join(lines)


def _format_sources(sources: list[NewsItem]) -> list[str]:
    lines = ["", "📎 <b>Источники:</b>"]
    for n in sources[:5]:
        lines.append(f'• <a href="{n.url}">{n.headline}</a> ({n.source})')
    return lines


def format_analyst_report(r: AnalystReport, low_data: bool = False,
                          sources: list[NewsItem] | None = None) -> str:
    conf = round(r.confidence * 100)
    if low_data:
        conf = min(conf, LOW_DATA_CONFIDENCE_CAP)
        conf_str = f"уверенность {conf}% · мало данных"
    else:
        conf_str = f"уверенность {conf}%"
    lines = [
        f"{STANCE_EMOJI[r.stance]} <b>{r.ticker}</b> — {r.stance} ({conf_str})",
        "",
        r.summary,
        "",
        "<b>Ключевое:</b>",
        *[f"• {p}" for p in r.key_points],
        "",
        "<b>Риски:</b>",
        *[f"⚠️ {p}" for p in r.risks],
    ]
    if sources:
        lines += _format_sources(sources)
    lines += ["", "<i>Это аналитический разбор, не инвестрекомендация.</i>"]
    return "\n".join(lines)
