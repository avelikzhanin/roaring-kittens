from roaring_kittens.committee.debate import build_debate_user, is_converged, run_debate_turn
from roaring_kittens.committee.schemas import DebateTurn, SpecialistView

VIEWS = [SpecialistView(role="news", stance="neutral", summary="s",
                        key_points=["k"], confidence=0.5)]


def _turn(speaker, position):
    return {"speaker": speaker, "argument": "a", "rebuttal_of": "-",
            "position_after": position}


def test_convergence_when_positions_match():
    assert is_converged([_turn("bull", "neutral"), _turn("bear", "neutral")]) is True
    assert is_converged([_turn("bull", "bullish"), _turn("bear", "bearish")]) is False
    assert is_converged([_turn("bull", "bullish")]) is False  # bear ещё не ходил


def test_debate_user_contains_views_and_history(council_ctx):
    text = build_debate_user(council_ctx, VIEWS, [_turn("bull", "bullish")], "bear")
    assert "news" in text and "БЫК" in text.upper()


class FakeLLM:
    def __init__(self):
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append((operation, model))
        return DebateTurn(argument="a", rebuttal_of="-", position_after="bullish")


async def test_turn_uses_o4_mini_and_role_op(council_ctx):
    llm = FakeLLM()
    turn = await run_debate_turn(llm, council_ctx, VIEWS, [], "bull")
    assert turn.position_after == "bullish"
    assert llm.ops == [("council_debate_bull", "o4-mini")]
