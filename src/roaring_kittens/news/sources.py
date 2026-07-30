"""Pluggable список RSS-источников. Добавить источник = добавить строку."""

SOURCES: list[tuple[str, str]] = [  # (source_id, url)
    ("rbc", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("interfax", "https://www.interfax.ru/rss.asp"),
    ("smartlab", "https://smart-lab.ru/rss/"),
]

# Crowd-источники: мнения толпы. Их читает ТОЛЬКО сентимент-аналитик комитета;
# в дайджест, алерты и проверку сделок/тезисов они не попадают.
CROWD_SOURCES: frozenset[str] = frozenset({"smartlab"})
