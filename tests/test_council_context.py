from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import roaring_kittens.committee.context as ctx_mod
from roaring_kittens.broker.models import Candle, PortfolioSnapshot
from roaring_kittens.committee.context import build_council_context
from roaring_kittens.news.models import NewsItem
from roaring_kittens.universe.universe import Instrument

INSTR = Instrument(ticker="SBER", figi="F", name="Сбер", aliases=frozenset())


def _news(source, headline):
    return NewsItem(source=source, url=f"https://x/{source}/{headline}", headline=headline,
                    body=None, published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])


class FakeSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class FakeBroker:
    async def get_daily_candles(self, figi, days=90):
        return [Candle(day=date(2026, 5, 1), open=Decimal(100), close=Decimal(100),
                       high=Decimal(101), low=Decimal(99), volume=1)]

    async def get_dividends(self, figi, years_back=3):
        return []

    async def get_portfolio(self):
        return PortfolioSnapshot(total_value=Decimal("0"), positions=[])


async def test_build_context_splits_news_and_survives_empty_account(monkeypatch):
    async def fake_news(session, tickers, since, limit=50):
        return [_news("rbc", "факт"), _news("smartlab", "мнение")]

    async def fake_last_call(session, ticker, within_days=7):
        return None

    async def fake_owner(session_factory):
        return 42

    async def fake_memory(deps, ticker, situation):
        return None

    monkeypatch.setattr(ctx_mod, "get_news_for_tickers", fake_news)
    monkeypatch.setattr(ctx_mod, "get_last_call", fake_last_call)
    monkeypatch.setattr(ctx_mod, "fetch_owner_id", fake_owner)
    monkeypatch.setattr(ctx_mod, "build_memory_note", fake_memory)
    deps = SimpleNamespace(broker=FakeBroker(), session_factory=lambda: FakeSession())

    ctx = await build_council_context(deps, INSTR, asked_by=42, today=date(2026, 7, 12))
    assert ctx.memory_note is None
    assert [n.headline for n in ctx.news_facts] == ["факт"]
    assert [n.headline for n in ctx.crowd_posts] == ["мнение"]
    assert ctx.tech is None                       # 1 свеча < MIN_CANDLES
    assert ctx.position_weight_pct is None        # пустой счёт
    assert "НЕТ" in ctx.position_note             # владелец, но бумаги нет
    assert "не выплачивались" in ctx.dividend_summary
    assert ctx.prev_call_note is None
