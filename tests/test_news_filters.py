from datetime import datetime, timezone

from roaring_kittens.news.filters import is_noise
from roaring_kittens.news.models import NewsItem

NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)


def _n(url, headline, body=None, source="rbc"):
    return NewsItem(source=source, url=url, headline=headline, body=body,
                    published_at=NOW)


def test_sport_sections_and_vtb_league_are_noise():
    assert is_noise(_n("https://www.rbc.ru/sport/17/08/2026/x", "Турнир перенесли"), NOW)
    assert is_noise(_n("https://sportrbc.ru/news/68da1", "Матч"), NOW)
    assert is_noise(_n("https://www.sport-interfax.ru/1117286", "Суперкубок",
                       source="interfax"), NOW)
    assert is_noise(_n("https://www.rbc.ru/business/04/09/2026/x",
                       "Иностранный клуб выиграл Суперкубок Единой лиги ВТБ"), NOW)
    assert is_noise(_n("https://www.rbc.ru/business/04/09/2026/x",
                       "ЦСКА обыграл «Зенит»", body="матч в Единой лиге ВТБ"), NOW)
    assert is_noise(_n("https://www.rbc.ru/business/04/09/2026/x",
                       "Концерт на ВТБ Арене"), NOW)


def test_rbc_url_date_older_than_3_days_is_stale_noise():
    # РБК бампит pubDate у старых материалов — верим дате в адресе
    assert is_noise(_n("https://www.rbc.ru/economics/20/08/2026/x", "Кадры"), NOW)
    assert not is_noise(_n("https://www.rbc.ru/economics/03/09/2026/x", "Свежее"), NOW)
    assert not is_noise(_n("https://www.interfax.ru/business/1112894", "Греф",
                           source="interfax"), NOW)
