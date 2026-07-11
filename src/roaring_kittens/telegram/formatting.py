from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.models import PortfolioSnapshot
from roaring_kittens.news.models import NewsItem
from roaring_kittens.scoring import TrackStats

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
                          sources: list[NewsItem] | None = None,
                          prev_note: str | None = None) -> str:
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
    if prev_note:
        lines += ["", prev_note]
    lines += ["", "<i>Это аналитический разбор, не инвестрекомендация.</i>"]
    return "\n".join(lines)


def format_prev_call_note(prev_stance: str, prev_confidence: float,
                          prev_at: datetime, new_stance: str, now: datetime) -> str:
    days = (now - prev_at).days
    when = "сегодня" if days == 0 else f"{days} дн назад"
    note = (f"🕰 Прошлый разбор ({when}): {STANCE_EMOJI[prev_stance]} {prev_stance} "
            f"{round(prev_confidence * 100)}%")
    if prev_stance != new_stance:
        note += " → ⚠️ мнение изменилось"
    return note


def format_track(stats: TrackStats, unscored: int) -> str:
    # «пока нет» — только когда нет НИ ОДНОЙ оценки ни на одном горизонте
    if not stats.per_horizon:
        return ("📊 <b>Track record</b>\n\nОценённых вызовов пока нет — "
                f"вызовы зреют минимум 5 дней (без единой оценки: {unscored}).")
    lines = ["📊 <b>Track record</b>"]
    parts = [f"{h}д: {v[0]}/{v[1]}" for h, v in sorted(stats.per_horizon.items())]
    lines.append("По горизонтам (hit/всего): " + " · ".join(parts))
    if stats.total_scored == 0:  # 5-дневные оценки есть, основное окно ещё зреет
        lines += ["", f"Основное окно ({stats.primary_horizon} дн) ещё зреет — "
                      "разбивка по ставкам появится позже.",
                  "", f"Без единой оценки: {unscored}"]
        return "\n".join(lines)
    lines += ["", f"Окно {stats.primary_horizon} дн — {stats.total_scored} оценённых:"]
    for stance in ("bullish", "bearish", "neutral"):
        if stance in stats.by_stance:
            hits, total = stats.by_stance[stance]
            lines.append(f"{STANCE_EMOJI[stance]} {stance}: {hits}/{total} hit")
    sign = "+" if stats.avg_excess_pp >= 0 else "−"
    lines.append(f"Средний результат vs IMOEX: {sign}{abs(stats.avg_excess_pp)} пп")
    baseline = round(stats.imoex_up_windows / stats.total_scored * 100)
    lines.append(f"Бейзлайн: IMOEX рос в {baseline}% этих окон")
    if stats.worst:
        lines += ["", "❌ <b>Худшие промахи:</b>"]
        for w in stats.worst:
            esign = "+" if w.excess_pp >= 0 else "−"  # знак честный: bearish-промах = плюс
            lines.append(f"• {w.ticker} {STANCE_EMOJI[w.stance]} {w.created_at:%d.%m} "
                         f"→ {esign}{abs(w.excess_pp)} пп vs IMOEX")
    lines += ["", f"Без единой оценки: {unscored} (вызовы зреют 5/20/60 дней)"]
    return "\n".join(lines)
