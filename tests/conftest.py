import os
from pathlib import Path

import pytest

# Пример: postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test
TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def db_session_factory():
    import asyncpg
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    raw = TEST_DB.replace("+asyncpg", "")
    schema = Path(__file__).resolve().parents[1].joinpath("db", "schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(raw)
    await conn.execute(schema)
    await conn.execute(
        "TRUNCATE news_events, usage_log, bot_state, council_runs, call_scores, "
        "calls, theses, insights, watchlists, alert_buffer, users, invites")
    await conn.close()

    engine = create_async_engine(TEST_DB)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def council_ctx():
    """Минимальный контекст комитета: тонкие данные, пустой счёт, гость."""
    from decimal import Decimal

    from roaring_kittens.broker.tech import Indicators
    from roaring_kittens.committee.context import CouncilContext

    return CouncilContext(
        ticker="SBER", tech=None,
        indicators=Indicators(rsi14=Decimal("43.2"), ma20=None, ma50=None,
                              volume_ratio=None),
        news_facts=[], crowd_posts=[], dividend_summary="Дивиденды: нет данных.",
        position_note=None, position_weight_pct=None, prev_call_note=None,
        memory_note=None)


@pytest.fixture
def scripted_council_llm():
    """LLM-сценарий комитета: bear сдаётся на 2-м раунде, PM=wait, Risk=approved."""
    from roaring_kittens.committee.schemas import (
        DebateTurn, Proposal, RiskReview, SpecialistView,
    )

    class ScriptedLLM:
        def __init__(self):
            self.ops = []
            self.bear_turns = 0

        async def parse(self, *, model, operation, messages, schema, temperature=None):
            self.ops.append(operation)
            if operation.startswith("council_debate_bull"):
                return DebateTurn(argument="за", rebuttal_of="-", position_after="bullish")
            if operation.startswith("council_debate_bear"):
                self.bear_turns += 1
                pos = "bearish" if self.bear_turns == 1 else "bullish"
                return DebateTurn(argument="против", rebuttal_of="-", position_after=pos)
            if operation == "council_manager":
                return Proposal(action="wait", stance="neutral", rationale="r",
                                thesis="t", invalidation="i", confidence=0.55)
            if operation == "council_risk":
                return RiskReview(approved=True, veto_reason=None, notes=[])
            return SpecialistView(role="news", stance="neutral", summary="s",
                                  key_points=["k"], confidence=0.5)

    return ScriptedLLM()
