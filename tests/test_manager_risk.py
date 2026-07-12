from dataclasses import replace
from decimal import Decimal

from roaring_kittens.committee.manager import run_manager
from roaring_kittens.committee.risk import hard_checks, run_risk
from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView

VIEWS = [SpecialistView(role="news", stance="neutral", summary="s",
                        key_points=["k"], confidence=0.5)]
PROPOSAL = Proposal(action="buy", stance="bullish", rationale="r", thesis="t",
                    invalidation="цена ниже 250", confidence=0.7)


def test_hard_checks_concentration_veto(council_ctx):
    fat = replace(council_ctx, position_weight_pct=Decimal("16"))
    vetoes = hard_checks(fat, PROPOSAL)
    assert any("Концентрация" in v for v in vetoes)
    # sell при большой позиции — концентрационного вето нет; берём confidence<=0.6,
    # чтобы не сработало И overconfidence-вето (ctx.tech is None). Оно намеренно
    # применяется к ЛЮБОМУ action — переуверенный sell так же вреден.
    sell = PROPOSAL.model_copy(update={"action": "sell", "confidence": 0.5})
    assert hard_checks(fat, sell) == []


def test_hard_checks_overconfidence_on_thin_data(council_ctx):
    vetoes = hard_checks(council_ctx, PROPOSAL)  # tech None, confidence 0.7 > 0.6
    assert any("тонких данных" in v for v in vetoes)


def test_hard_checks_empty_account_no_weight_veto(council_ctx):
    assert not any("Концентрация" in v
                   for v in hard_checks(council_ctx, PROPOSAL))  # weight None -> пропуск


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.ops = []

    async def parse(self, *, model, operation, messages, schema, temperature=None):
        self.ops.append((operation, model))
        return self.result


async def test_manager_op_and_model(council_ctx):
    llm = FakeLLM(PROPOSAL)
    p = await run_manager(llm, council_ctx, VIEWS, [])
    assert p.action == "buy"
    assert llm.ops == [("council_manager", "gpt-4o")]


async def test_risk_hard_veto_overrides_llm_approval(council_ctx):
    llm = FakeLLM(RiskReview(approved=True, veto_reason=None, notes=["ok"]))
    review = await run_risk(llm, council_ctx, PROPOSAL, vetoes=["Концентрация: 16%"])
    assert review.approved is False and "Концентрация" in review.veto_reason
    assert llm.ops[0] == ("council_risk", "o4-mini")


async def test_risk_llm_veto_respected(council_ctx):
    llm = FakeLLM(RiskReview(approved=False, veto_reason="волатильность", notes=[]))
    review = await run_risk(llm, council_ctx, PROPOSAL, vetoes=[])
    assert review.approved is False and review.veto_reason == "волатильность"
