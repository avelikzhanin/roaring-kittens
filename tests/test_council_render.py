from roaring_kittens.committee.render import (
    chunk_lines, format_council_protocol, format_council_verdict,
)
from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView

VIEWS = [SpecialistView(role="news", stance="bearish", summary="плохие новости",
                        key_points=["k"], confidence=0.6),
         SpecialistView(role="technical", stance="bullish", summary="отскок",
                        key_points=["k"], confidence=0.7)]
DEBATE = [{"speaker": "bull", "argument": "за рост", "rebuttal_of": "-",
           "position_after": "bullish"},
          {"speaker": "bear", "argument": "против", "rebuttal_of": "-",
           "position_after": "bearish"}]
PROPOSAL = Proposal(action="wait", stance="neutral", rationale="ждём отчёта",
                    thesis="тезис", invalidation="цена ниже 250", confidence=0.55)


def test_verdict_contains_action_thesis_and_votes():
    text = format_council_verdict("SBER", VIEWS, DEBATE, PROPOSAL,
                                  RiskReview(approved=True, notes=[]))
    assert "SBER" in text and "ждать" in text.lower()
    assert "тезис" in text and "цена ниже 250" in text
    assert "📰" in text and "📈" in text          # иконки ролей
    assert "1 раунд" in text


def test_verdict_shows_veto():
    text = format_council_verdict("SBER", VIEWS, DEBATE, PROPOSAL,
                                  RiskReview(approved=False, veto_reason="концентрация"))
    assert "⛔️" in text and "концентрация" in text


def test_protocol_chunks_under_limit():
    chunks = format_council_protocol(VIEWS, DEBATE, PROPOSAL,
                                     RiskReview(approved=True, notes=["n"]))
    assert all(len(c) <= 3500 for c in chunks)
    assert "плохие новости" in chunks[0]


def test_chunk_lines_splits():
    chunks = chunk_lines(["x" * 100] * 50, limit=1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks)


def test_chunk_lines_hard_splits_single_overlong_line():
    chunks = chunk_lines(["x" * 5000], limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert sum(len(c) for c in chunks) == 5000
