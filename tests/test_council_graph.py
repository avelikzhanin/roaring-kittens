from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.schemas import DebateTurn, Proposal, RiskReview, SpecialistView


class ScriptedLLM:
    """bull всегда bullish; bear: 1-й ход bearish, 2-й — сдаётся в bullish (сходимость на 2 раунде)."""

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


async def test_graph_runs_end_to_end_with_early_convergence(council_ctx):
    llm = ScriptedLLM()
    graph = build_council_graph(llm)
    state = await graph.ainvoke({"ctx": council_ctx})
    assert state["proposal"].action == "wait"
    assert state["risk"].approved is True
    assert len(state["views"]) == 4
    # 2 раунда дебатов (bear сдался на втором) => 4 хода, не 6
    assert len(state["debate"]) == 4
    assert state["round"] == 2
    # порядок: 4 специалиста -> дебаты -> manager -> risk
    assert llm.ops[-2:] == ["council_manager", "council_risk"]
    assert llm.ops.count("council_debate_bull") == 2
    assert llm.ops.count("council_debate_bear") == 2
