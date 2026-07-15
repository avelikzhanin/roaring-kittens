from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import roaring_kittens.committee.memory as mem_mod
from roaring_kittens.committee.memory import MEMORY_CHAR_CAP, build_memory_note
from roaring_kittens.db.calls import ScoredCall, SimilarCall
from roaring_kittens.db.insights import InsightRecord

NOW = datetime.now(tz=timezone.utc)


class FakeSession:
    async def __aenter__(self):
        return self  # ВАЖНО: self, а не object() — build_memory_note зовёт session.commit()

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


class FakeEmbedder:
    async def embed(self, text, operation):
        return [0.0] * 1536


def _similar(ticker, verdict=None):
    score = None
    if verdict:
        score = ScoredCall(ticker=ticker, stance="bullish", created_at=NOW, source="ask",
                           horizon_days=20, stock_return_pct=Decimal("5"),
                           imoex_return_pct=Decimal("1"), verdict=verdict)
    return SimilarCall(ticker=ticker, stance="bullish", created_at=NOW,
                       summary="рост на отчёте", score_20d=score)


async def test_memory_note_contains_similar_and_insights(monkeypatch):
    async def fake_similar(session, emb, k=3):
        return [_similar("GAZP", "hit")]

    async def fake_insights(session, emb, k=3, min_confidence=0.5):
        return [InsightRecord(id=uuid4(), created_at=NOW, summary="банки под дивы работают",
                              scope="pattern", scope_value="x", confidence=0.8,
                              times_applied=0)]

    async def fake_bump(session, ids):
        fake_bump.called = ids
    fake_bump.called = None

    monkeypatch.setattr(mem_mod, "find_similar_calls", fake_similar)
    monkeypatch.setattr(mem_mod, "top_insights_by_similarity", fake_insights)
    monkeypatch.setattr(mem_mod, "bump_times_applied", fake_bump)
    deps = SimpleNamespace(embedder=FakeEmbedder(), session_factory=lambda: FakeSession())

    note = await build_memory_note(deps, "SBER", "SBER: рост на объёме")
    assert "GAZP" in note and "hit" in note
    assert "банки под дивы" in note
    assert len(note) <= MEMORY_CHAR_CAP
    assert fake_bump.called is not None  # применённые уроки посчитаны


async def test_memory_note_none_when_empty(monkeypatch):
    async def none_similar(session, emb, k=3):
        return []

    async def none_insights(session, emb, k=3, min_confidence=0.5):
        return []

    monkeypatch.setattr(mem_mod, "find_similar_calls", none_similar)
    monkeypatch.setattr(mem_mod, "top_insights_by_similarity", none_insights)
    deps = SimpleNamespace(embedder=FakeEmbedder(), session_factory=lambda: FakeSession())
    assert await build_memory_note(deps, "SBER", "ситуация") is None
