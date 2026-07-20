from datetime import datetime, timezone

from roaring_kittens.committee.impact import (
    ImpactCheck, decide_impact_action, run_impact_check,
)
from roaring_kittens.news.models import NewsItem


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_impact_check_uses_mini():
    llm = FakeLLM(ImpactCheck(impact="high", direction="bearish",
                              reasoning_short="дивы ниже консенсуса"))
    news = [NewsItem(source="rbc", url="https://x/1",
                     headline="ВТБ рекомендовал дивиденды ниже ожиданий", body=None,
                     published_at=datetime.now(tz=timezone.utc), tickers=["VTBR"])]
    check = await run_impact_check(llm, "VTBR", news)
    assert check.impact == "high"
    assert llm.calls == [("impact_check", "gpt-4o-mini")]


def test_decide_impact_action_matrix():
    assert decide_impact_action("critical", council_recent=True) == "council_critical"
    assert decide_impact_action("critical", council_recent=False) == "council_critical"
    assert decide_impact_action("high", council_recent=False) == "council"
    assert decide_impact_action("high", council_recent=True) == "notify"
    assert decide_impact_action("medium", council_recent=False) == "notify"
    assert decide_impact_action("low", council_recent=False) == "nothing"
    assert decide_impact_action("noise", council_recent=False) == "nothing"
