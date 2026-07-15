from datetime import datetime, timezone

from roaring_kittens.committee.thesis_check import (
    ThesisCheck, decide_validation_action, run_thesis_check,
)
from roaring_kittens.committee.thesis_gen import ThesisDraft, run_thesis_draft
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.news.models import NewsItem


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_thesis_draft_op_and_model(council_ctx):
    llm = FakeLLM(ThesisDraft(thesis="дивидендная история",
                              invalidation="отмена дивидендов", confidence=0.6))
    draft = await run_thesis_draft(llm, council_ctx)
    assert "дивидендная" in draft.thesis
    assert llm.calls == [("thesis_draft", "gpt-4o")]


def _thesis():
    return ThesisRecord(id=None, ticker="SBER", figi="F",
                        opened_at=datetime.now(tz=timezone.utc), closed_at=None,
                        status="active", thesis="рост под дивиденды",
                        invalidation="дивы отменены или ниже 20 ₽", source="auto",
                        confidence=0.6, entry_price=None, realized_return_pct=None,
                        close_reason=None)


async def test_thesis_check_uses_mini_and_returns_status():
    llm = FakeLLM(ThesisCheck(status="invalidated", reasoning_short="дивы отменили"))
    news = [NewsItem(source="rbc", url="https://x/1",
                     headline="Сбер отменил дивиденды",
                     body=None, published_at=datetime.now(tz=timezone.utc),
                     tickers=["SBER"])]
    check = await run_thesis_check(llm, _thesis(), news)
    assert check.status == "invalidated"
    assert llm.calls == [("thesis_check", "gpt-4o-mini")]


def test_decide_validation_action():
    assert decide_validation_action("invalidated", council_recent=False) == "council"
    assert decide_validation_action("invalidated", council_recent=True) == "notify"
    assert decide_validation_action("weakened", council_recent=False) == "notify"
    assert decide_validation_action("still_valid", council_recent=False) == "nothing"
