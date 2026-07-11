import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest
from roaring_kittens.news.matching import match_tickers
from roaring_kittens.scoring import score_due_calls
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


async def morning_digest_job(deps: Deps, bot) -> None:
    """Утренний дайджест шлём владельцу (первый /start). Пока владельца нет — скипаем."""
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        log.warning("digest_skipped_no_owner")
        return
    await run_morning_digest(deps, bot, owner_id)


def build_scheduler(deps: Deps, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=deps.settings.tz)
    scheduler.add_job(poll_news, "interval", minutes=30, args=[deps],
                      id="poll_news", max_instances=1, coalesce=True)
    scheduler.add_job(morning_digest_job, "cron", hour=9, minute=0,
                      args=[deps, bot],
                      id="morning_digest", max_instances=1, coalesce=True)
    scheduler.add_job(score_due_calls, "cron", hour=23, minute=45, args=[deps],
                      id="score_calls", max_instances=1, coalesce=True)
    return scheduler
