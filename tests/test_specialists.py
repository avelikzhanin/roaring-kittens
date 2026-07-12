from roaring_kittens.committee.schemas import SpecialistView
from roaring_kittens.committee.specialists import (
    ROLE_PROMPTS, build_specialist_user, run_specialists,
)


class FakeLLM:
    def __init__(self):
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append(operation)
        return SpecialistView(role="news", stance="neutral", summary="s",
                              key_points=["k"], confidence=0.5)


async def test_runs_all_four_roles_and_fixes_role_field(council_ctx):
    llm = FakeLLM()
    views = await run_specialists(llm, council_ctx)
    assert sorted(v.role for v in views) == ["fundamentals", "news", "sentiment", "technical"]
    assert sorted(llm.ops) == ["council_fundamentals", "council_news",
                               "council_sentiment", "council_technical"]


def test_each_role_gets_its_data_slice(council_ctx):
    assert "RSI(14): 43.2" in build_specialist_user(council_ctx, "technical")
    assert "Дивиденды" in build_specialist_user(council_ctx, "fundamentals")
    assert "новостей нет" in build_specialist_user(council_ctx, "news").lower()
    assert "постов нет" in build_specialist_user(council_ctx, "sentiment").lower()
