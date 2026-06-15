from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    source: str
    url: str
    headline: str
    body: str | None
    published_at: datetime
    tickers: list[str] = field(default_factory=list)
