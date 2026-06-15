import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest
from roaring_kittens.news.matching import match_tickers
from roaring_kittens.news.repository import save_news
from roaring_kittens.news.rss import fetch_feed
from roaring_kittens.news.sources import SOURCES

log = structlog.get_logger()


async def poll_news(deps: Deps) -> None:
    alias_map = deps.universe.alias_map()
    total_inserted = 0
    for source_id, url in SOURCES:
        items = await fetch_feed(url, source=source_id)
        for item in items:
            item.tickers = match_tickers(f"{item.headline} {item.body or ''}", alias_map)
        relevant = [i for i in items if i.tickers]
        async with deps.session_factory() as session:
            inserted = await save_news(session, relevant)
            await session.commit()
        total_inserted += inserted
        log.info("news_polled", source=source_id, fetched=len(items),
                 relevant=len(relevant), inserted=inserted)
    log.info("news_poll_done", inserted=total_inserted)


def build_scheduler(deps: Deps, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=deps.settings.tz)
    scheduler.add_job(poll_news, "interval", minutes=30, args=[deps],
                      id="poll_news", max_instances=1, coalesce=True)
    scheduler.add_job(run_morning_digest, "cron", hour=9, minute=0,
                      args=[deps, bot, deps.settings.admin_telegram_id],
                      id="morning_digest", max_instances=1, coalesce=True)
    return scheduler
