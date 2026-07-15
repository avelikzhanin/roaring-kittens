from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import roaring_kittens.reflection as refl_mod
from roaring_kittens.db.calls import ScoredCall
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.reflection import (
    ReflectionOutput, build_reflection_user, run_reflection,
)

NOW = datetime.now(tz=timezone.utc)


def _closed_thesis():
    return ThesisRecord(id=uuid4(), ticker="GAZP", figi="F", opened_at=NOW,
                        closed_at=NOW, status="closed", thesis="рост на контракте",
                        invalidation="i", source="auto", confidence=0.6,
                        entry_price=None, realized_return_pct=Decimal("-3.5"),
                        close_reason="позиция закрыта", backed_by_position=True)


def _scored(verdict="miss"):
    return ScoredCall(ticker="GAZP", stance="bullish", created_at=NOW, source="ask",
                      horizon_days=20, stock_return_pct=Decimal("-2"),
                      imoex_return_pct=Decimal("1.5"), verdict=verdict, scored_at=NOW)


def test_reflection_user_contains_material():
    text = build_reflection_user([_closed_thesis()], [_scored()])
    assert "GAZP" in text and "-3.5" in text
    assert "miss" in text


async def test_run_reflection_skips_when_no_material():
    llm = SimpleNamespace()  # не должен вызываться
    result = await run_reflection(llm, [], [])
    assert result is None


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.calls.append((operation, model))
        return self.result


async def test_run_reflection_returns_output():
    out = ReflectionOutput(weekly_summary="неделя так себе",
                           insights=[refl_mod.InsightDraft(
                               summary="газ не растёт на контрактах",
                               scope="ticker", scope_value="GAZP", confidence=0.6)])
    llm = FakeLLM(out)
    result = await run_reflection(llm, [_closed_thesis()], [_scored()])
    assert result is out
    assert llm.calls == [("weekly_reflection", "gpt-4o")]
