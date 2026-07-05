from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.digest.morning import build_digest_text
from roaring_kittens.news.models import NewsItem

SNAP = PortfolioSnapshot(
    total_value=Decimal("1000000"),
    positions=[Position(ticker="SBER", name="Сбер", figi="F", quantity=Decimal("500"),
                        avg_price=Decimal("280"), current_price=Decimal("294"),
                        pnl_pct=Decimal("5.0"))],
)
NEWS = {"SBER": [NewsItem(source="rbc", url="https://x/1", headline="Сбер: рекордная прибыль",
                          body=None, published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])]}


def test_build_digest_contains_portfolio_news_and_ai():
    text = build_digest_text(SNAP, NEWS, ai_summary="Рынок спокоен, следи за ЦБ.")
    assert "Портфель" in text and "SBER" in text
    assert "Сбер: рекордная прибыль" in text
    assert "Рынок спокоен" in text


def test_build_digest_renders_news_as_clickable_links():
    text = build_digest_text(SNAP, NEWS, ai_summary=None)
    assert '<a href="https://x/1">Сбер: рекордная прибыль</a>' in text


def test_build_digest_without_news():
    text = build_digest_text(SNAP, {}, ai_summary=None)
    assert "нет свежих новостей" in text.lower()
