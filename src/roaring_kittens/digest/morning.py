from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.deps import Deps
from roaring_kittens.news.models import NewsItem
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.telegram.formatting import STANCE_EMOJI, format_portfolio

log = structlog.get_logger()

DIGEST_MODEL = "gpt-4o"


class DigestSummary(BaseModel):
    market_comment: str = Field(description="2-3 предложения: что важного для портфеля из новостей")
    watch_today: list[str] = Field(description="0-3 пункта: за чем следить сегодня")


DIGEST_SYSTEM = """Ты — утренний аналитик-ассистент частного инвестора на Мосбирже.
По его портфелю и ночным новостям дай короткий комментарий: что важно, за чем следить.
Не выдумывай числа и события. Если новостей мало — так и скажи. Пиши по-русски."""


def build_digest_text(snap: PortfolioSnapshot, news_by_ticker: dict[str, list[NewsItem]],
                      ai_summary: str | None) -> str:
    parts = ["☀️ <b>Доброе утро!</b>", "", format_portfolio(snap), ""]
    if news_by_ticker:
        parts.append("📰 <b>Новости по позициям:</b>")
        for ticker, items in news_by_ticker.items():
            for n in items[:3]:
                parts.append(f'• <b>{ticker}</b>: <a href="{n.url}">{n.headline}</a>')
        parts.append("")
    else:
        parts.append("📰 По твоим позициям нет свежих новостей.\n")
    if ai_summary:
        parts.append(f"🤖 {ai_summary}")
    return "\n".join(parts)


async def build_spotlight(deps: Deps, position: Position) -> str | None:
    """Разбор дня для тихого утра (нет новостей) — переиспользует одиночный аналитик."""
    try:
        candles = await deps.broker.get_daily_candles(position.figi)
        tech = compute_tech_summary(candles)
        report = await run_analyst(deps.llm, position.ticker, tech, [], None)
    except Exception as exc:
        log.error("spotlight_failed", ticker=position.ticker, error=str(exc))
        return None
    emoji = STANCE_EMOJI.get(report.stance, "")
    return f"🔎 <b>Разбор дня — {position.ticker}</b> {emoji}\n{report.summary}"


async def run_morning_digest(deps: Deps, bot, chat_id: int) -> None:
    snap = await deps.broker.get_portfolio()
    tickers = [p.ticker for p in snap.positions]
    since = datetime.now(tz=timezone.utc) - timedelta(hours=16)
    news_by_ticker: dict[str, list[NewsItem]] = {}
    if tickers:
        async with deps.session_factory() as session:
            all_news = await get_news_for_tickers(session, tickers, since=since)
        for n in all_news:
            for t in n.tickers:
                if t in tickers:
                    news_by_ticker.setdefault(t, []).append(n)

    ai_summary = None
    if news_by_ticker:
        headlines = "\n".join(f"- {t}: {n.headline}" for t, items in news_by_ticker.items()
                              for n in items[:3])
        positions = ", ".join(f"{p.ticker} ({p.pnl_pct:+}%)" for p in snap.positions)
        try:
            result = await deps.llm.parse(
                model=DIGEST_MODEL, operation="morning_digest",
                messages=[{"role": "system", "content": DIGEST_SYSTEM},
                          {"role": "user", "content": f"Портфель: {positions}\n\nНовости:\n{headlines}"}],
                schema=DigestSummary,
            )
            watch = "".join(f"\n• {w}" for w in result.watch_today)
            ai_summary = result.market_comment + (f"\n\n👀 <b>Следить:</b>{watch}" if watch else "")
        except Exception as exc:
            log.error("digest_llm_failed", error=str(exc))

    text = build_digest_text(snap, news_by_ticker, ai_summary)

    # Тихое утро: новостей нет, но дайджест не должен быть пустым — даём разбор дня по ротации.
    if not news_by_ticker and snap.positions:
        idx = datetime.now(tz=timezone.utc).timetuple().tm_yday % len(snap.positions)
        spotlight = await build_spotlight(deps, snap.positions[idx])
        if spotlight:
            text += "\n\n" + spotlight

    await bot.send_message(chat_id, text)
    log.info("digest_sent", tickers=len(tickers), with_ai=ai_summary is not None,
             quiet_day=not news_by_ticker)
