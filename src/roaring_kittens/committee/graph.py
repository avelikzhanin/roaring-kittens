from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged, run_debate_turn
from roaring_kittens.committee.manager import run_manager
from roaring_kittens.committee.risk import hard_checks, run_risk
from roaring_kittens.committee.specialists import run_specialists


class CouncilState(TypedDict, total=False):
    ctx: Any
    views: list
    debate: list
    round: int
    proposal: Any
    risk: Any


def build_council_graph(llm):
    async def specialists_node(state: CouncilState):
        views = await run_specialists(llm, state["ctx"])
        return {"views": views, "debate": [], "round": 0}

    async def bull_node(state: CouncilState):
        turn = await run_debate_turn(llm, state["ctx"], state["views"],
                                     state["debate"], "bull")
        return {"debate": state["debate"] + [{"speaker": "bull", **turn.model_dump()}]}

    async def bear_node(state: CouncilState):
        turn = await run_debate_turn(llm, state["ctx"], state["views"],
                                     state["debate"], "bear")
        return {"debate": state["debate"] + [{"speaker": "bear", **turn.model_dump()}],
                "round": state["round"] + 1}

    def after_bear(state: CouncilState) -> str:
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return "manager"
        return "bull"

    async def manager_node(state: CouncilState):
        proposal = await run_manager(llm, state["ctx"], state["views"], state["debate"])
        return {"proposal": proposal}

    async def risk_node(state: CouncilState):
        vetoes = hard_checks(state["ctx"], state["proposal"])
        review = await run_risk(llm, state["ctx"], state["proposal"], vetoes)
        return {"risk": review}

    g = StateGraph(CouncilState)
    g.add_node("specialists", specialists_node)
    g.add_node("bull", bull_node)
    g.add_node("bear", bear_node)
    g.add_node("manager", manager_node)
    g.add_node("risk", risk_node)
    g.add_edge(START, "specialists")
    g.add_edge("specialists", "bull")
    g.add_edge("bull", "bear")
    g.add_conditional_edges("bear", after_bear, {"bull": "bull", "manager": "manager"})
    g.add_edge("manager", "risk")
    g.add_edge("risk", END)
    return g.compile()
