from roaring_kittens.committee.graph import build_council_graph


async def test_graph_runs_end_to_end_with_early_convergence(council_ctx,
                                                            scripted_council_llm):
    llm = scripted_council_llm
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
