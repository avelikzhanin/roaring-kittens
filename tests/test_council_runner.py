from types import SimpleNamespace

import roaring_kittens.committee.runner as runner_mod
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.universe.universe import Instrument

INSTR = Instrument(ticker="SBER", figi="F", name="Сбер", aliases=frozenset())


async def test_runner_returns_outcome_and_persists(council_ctx, scripted_council_llm,
                                                   monkeypatch):
    stages = []
    saved = {}

    async def fake_persist(deps, instrument, asked_by, ctx, state):
        saved["state"] = state
        return ("call-id", "run-id")

    monkeypatch.setattr(runner_mod, "_persist_council", fake_persist)
    deps = SimpleNamespace(llm=scripted_council_llm)

    async def on_stage(text):
        stages.append(text)

    outcome = await run_council_flow(deps, INSTR, asked_by=42, ctx=council_ctx,
                                     on_stage=on_stage)
    assert outcome.proposal.action == "wait" and outcome.risk.approved
    assert outcome.call_id == "call-id" and outcome.run_id == "run-id"
    assert len(outcome.state["debate"]) == 4
    assert any("Bull vs Bear" in s for s in stages)   # стадии анонсировались
    assert saved["state"]["proposal"].action == "wait"
