from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx
import structlog

from roaring_kittens.news.models import NewsItem

log = structlog.get_logger()


async def fetch_feed(url: str, source: str,
                     transport: httpx.BaseTransport | None = None) -> list[NewsItem]:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=15,
                                     follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        log.warning("rss_fetch_failed", source=source, error=str(exc))
        return []
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        if not getattr(e, "link", None) or not getattr(e, "title", None):
            continue
        if getattr(e, "published_parsed", None):
            published = datetime.fromtimestamp(mktime(e.published_parsed), tz=timezone.utc)
        else:
            published = datetime.now(tz=timezone.utc)
        items.append(NewsItem(
            source=source, url=e.link, headline=e.title,
            body=getattr(e, "summary", None), published_at=published,
        ))
    return items
