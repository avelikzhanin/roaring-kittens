"""Что НЕ считается новостью компании: спорт под брендом банка и «старые по
адресу» статьи РБК (сентябрь 2026: «лига ВТБ» и Халк Хоган в дайджесте)."""
import re
from datetime import datetime, timedelta

from roaring_kittens.news.models import NewsItem

SPORT_URL_MARKERS = ("/sport/", "sportrbc.ru", "sport-interfax.ru")
SPORT_TEXT_RE = re.compile(r"лиг[аиеу] ВТБ|ВТБ[\s-]?Арен", re.IGNORECASE)
RBC_URL_DATE_RE = re.compile(r"/(\d{2})/(\d{2})/(\d{4})/")
STALE_URL_DAYS = 3


def is_noise(item: NewsItem, now: datetime) -> bool:
    url = item.url.lower()
    if any(m in url for m in SPORT_URL_MARKERS):
        return True
    # тот же текст, что и у матчинга тикеров (headline+body): «лига ВТБ» в теле
    # статьи иначе всё равно попала бы в дайджест
    if SPORT_TEXT_RE.search(f"{item.headline} {item.body or ''}"):
        return True
    m = RBC_URL_DATE_RE.search(item.url)
    if m:  # РБК бампит pubDate у старых материалов — верим дате в адресе
        day, month, year = (int(x) for x in m.groups())
        try:
            url_date = datetime(year, month, day, tzinfo=now.tzinfo)
        except ValueError:
            return False
        if now - url_date > timedelta(days=STALE_URL_DAYS):
            return True
    return False
