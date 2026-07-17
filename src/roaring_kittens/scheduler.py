from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from roaring_kittens.committee.render import format_council_verdict
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.committee.thesis_check import decide_validation_action, run_thesis_check
from roaring_kittens.db.calls import council_ran_recently
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import close_thesis, get_active_theses, mark_thesis_weakened
from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest
from roaring_kittens.news.matching import match_tickers
from roaring_kittens.news.repository import save_news
from roaring_kittens.news.rss import fetch_feed
from roaring_kittens.news.sources import SOURCES
from roaring_kittens.positions_sync import sync_positions
from roaring_kittens.reflection import weekly_reflection_job
from roaring_kittens.scoring import score_due_calls
from roaring_kittens.telegram.formatting import esc

log = structlog.get_logger()


async def poll_news(deps: Deps, bot=None) -> None:
    alias_map = deps.universe.alias_map()
    fresh_items = []  # ТОЛЬКО реально вставленные новости — точность вместо окна
    for source_id, url in SOURCES:
        items = await fetch_feed(url, source=source_id)
        for item in items:
            item.tickers = match_tickers(f"{item.headline} {item.body or ''}", alias_map)
        relevant = [i for i in items if i.tickers]
        async with deps.session_factory() as session:
            inserted_urls = await save_news(session, relevant)
            await session.commit()
        fresh_items += [i for i in relevant if i.url in set(inserted_urls)]
        log.info("news_polled", source=source_id, fetched=len(items),
                 relevant=len(relevant), inserted=len(inserted_urls))
    log.info("news_poll_done", inserted=len(fresh_items))
    if bot is not None and fresh_items:
        try:
            await validate_theses(deps, bot, fresh_items)
        except Exception as exc:
            log.error("validate_theses_failed", error=str(exc))


GENERIC_NEWS_TICKER_CAP = 3   # пост с 4+ тикерами = обзор рынка, не событие компании
WEAKENED_COOLDOWN = timedelta(hours=24)


async def validate_theses(deps, bot, fresh_items: list) -> None:
    """Проверка активных тезисов ТОЛЬКО реально новыми новостями (без окна — без спама)."""
    if not fresh_items:
        return
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    by_ticker: dict[str, list] = {}
    for item in fresh_items:
        # обзорные посты («Индекс МБ сегодня»), матчащиеся на пол-универсума,
        # не считаем событием конкретной компании — тезисы ими не проверяем
        if len(item.tickers) > GENERIC_NEWS_TICKER_CAP:
            continue
        for t in item.tickers:
            by_ticker.setdefault(t, []).append(item)
    async with deps.session_factory() as session:
        theses_to_check = [t for t in await get_active_theses(session)
                           if t.ticker in by_ticker]
    for thesis in theses_to_check:
        news = by_ticker[thesis.ticker]
        async with deps.session_factory() as session:
            recent = await council_ran_recently(session, thesis.ticker, hours=24)
        try:
            check = await run_thesis_check(deps.llm, thesis, news)
        except Exception as exc:
            log.error("thesis_check_failed", ticker=thesis.ticker, error=str(exc))
            continue
        action = decide_validation_action(check.status, recent)
        if action == "nothing":
            continue
        if action == "notify":
            if check.status == "weakened":
                last = thesis.last_weakened_at
                if last and datetime.now(tz=timezone.utc) - last < WEAKENED_COOLDOWN:
                    log.info("weakened_suppressed_cooldown", ticker=thesis.ticker)
                    continue
                async with deps.session_factory() as session:
                    await mark_thesis_weakened(session, thesis.id)
                    await session.commit()
            await bot.send_message(
                owner_id,
                f"⚠️ Тезис по <b>{thesis.ticker}</b> "
                f"{'СЛОМАН' if check.status == 'invalidated' else 'ослаблен'}: "
                f"{esc(check.reasoning_short)}\nТезис: {esc(thesis.thesis)}")
            continue
        # action == "council": автозапуск комитета
        await bot.send_message(
            owner_id,
            f"🚨 Новости ломают тезис по <b>{thesis.ticker}</b>: "
            f"{esc(check.reasoning_short)}\nСобираю комитет…")
        instrument = deps.universe.resolve(thesis.ticker)
        if instrument is None:
            continue
        try:
            outcome = await run_council_flow(deps, instrument, owner_id)
        except Exception as exc:
            log.error("auto_council_failed", ticker=thesis.ticker, error=str(exc))
            continue
        async with deps.session_factory() as session:
            await close_thesis(session, thesis.id, status="invalidated",
                               realized_return_pct=None,
                               close_reason=f"новости: {check.reasoning_short}")
            await session.commit()
        # Комитет предложил замену старому тезису — даём принять кнопкой
        keyboard = None
        if outcome.run_id is not None:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                             callback_data=f"proto:{outcome.run_id}")]]
            if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
                buttons.append([InlineKeyboardButton(
                    text="📌 Принять новый тезис",
                    callback_data=f"thesis_save:{outcome.run_id}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await bot.send_message(
            owner_id,
            format_council_verdict(instrument.ticker, outcome.state["views"],
                                   outcome.state["debate"], outcome.proposal,
                                   outcome.risk),
            reply_markup=keyboard)


async def morning_digest_job(deps: Deps, bot) -> None:
    """Утренний дайджест шлём владельцу (первый /start). Пока владельца нет — скипаем."""
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        log.warning("digest_skipped_no_owner")
        return
    await run_morning_digest(deps, bot, owner_id)


def build_scheduler(deps: Deps, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=deps.settings.tz)
    scheduler.add_job(poll_news, "interval", minutes=30, args=[deps, bot],
                      id="poll_news", max_instances=1, coalesce=True)
    scheduler.add_job(morning_digest_job, "cron", hour=9, minute=0,
                      args=[deps, bot],
                      id="morning_digest", max_instances=1, coalesce=True)
    scheduler.add_job(score_due_calls, "cron", hour=23, minute=45, args=[deps],
                      id="score_calls", max_instances=1, coalesce=True)
    scheduler.add_job(sync_positions, "cron", hour=8, minute=50, args=[deps, bot],
                      id="positions_sync", max_instances=1, coalesce=True)
    scheduler.add_job(weekly_reflection_job, "cron", day_of_week="sun",
                      hour=23, minute=0, args=[deps, bot],
                      id="weekly_reflection", max_instances=1, coalesce=True)
    return scheduler
