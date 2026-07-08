from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from roaring_kittens.ai.analyst import build_analyst_messages, run_analyst
from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.tech import TechSummary
from roaring_kittens.news.models import NewsItem

TECH = TechSummary(last_close=Decimal("295"), change_1d_pct=Decimal("0.5"),
                   change_7d_pct=Decimal("2.1"), change_30d_pct=Decimal("5.4"),
                   high_30d=Decimal("298"), low_30d=Decimal("279"))
NEWS = [NewsItem(source="rbc", url="https://x/1", headline="Сбер показал рекордную прибыль",
                 body="детали", published_at=datetime.now(tz=timezone.utc), tickers=["SBER"])]


def test_messages_contain_data_and_guardrails():
    msgs = build_analyst_messages("SBER", TECH, NEWS, question="докупать?")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "не выдумывай числа" in system.lower()
    assert "295" in user and "Сбер показал рекордную прибыль" in user
    assert "докупать?" in user


async def test_run_analyst_calls_llm_with_schema():
    fake_llm = AsyncMock()
    fake_llm.parse.return_value = AnalystReport(
        ticker="SBER", stance="bullish", summary="s", key_points=["k"], risks=["r"], confidence=0.8)
    report = await run_analyst(fake_llm, "SBER", TECH, NEWS, question=None)
    assert report.stance == "bullish"
    kwargs = fake_llm.parse.call_args.kwargs
    assert kwargs["schema"] is AnalystReport
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["operation"] == "analyst"
    assert "temperature" not in kwargs  # дефолт модели, решение owner'а
