"""Pluggable список RSS-источников. Добавить источник = добавить строку.
e-disclosure: глобального RSS нет, пер-компанийные фиды добавим в Фазе 4."""

SOURCES: list[tuple[str, str]] = [  # (source_id, url)
    ("rbc", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("smartlab", "https://smart-lab.ru/rss/"),
]
