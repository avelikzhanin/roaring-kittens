import httpx

from roaring_kittens.news.rss import fetch_feed

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item>
  <title>Сбербанк отчитался о рекордной прибыли</title>
  <link>https://example.com/news/1</link>
  <description>Прибыль выросла на 20%</description>
  <pubDate>Wed, 11 Jun 2026 09:30:00 +0300</pubDate>
</item>
<item>
  <title>Газпром подписал контракт</title>
  <link>https://example.com/news/2</link>
  <description>Детали контракта</description>
  <pubDate>Wed, 11 Jun 2026 10:00:00 +0300</pubDate>
</item>
</channel></rss>"""


async def test_fetch_feed_parses_entries():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=RSS_XML.encode()))
    entries = await fetch_feed("https://example.com/rss", source="test", transport=transport)
    assert len(entries) == 2
    e = entries[0]
    assert e.headline == "Сбербанк отчитался о рекордной прибыли"
    assert e.url == "https://example.com/news/1"
    assert e.body == "Прибыль выросла на 20%"
    assert e.published_at.year == 2026 and e.source == "test"


async def test_fetch_feed_http_error_returns_empty():
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    assert await fetch_feed("https://example.com/rss", source="test", transport=transport) == []
