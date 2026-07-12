from decimal import Decimal

from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import Proposal, RiskReview

RISK_MODEL = "o4-mini"
MAX_POSITION_WEIGHT_PP = Decimal("15")
OVERCONFIDENCE_THRESHOLD = 0.6

RISK_SYSTEM = """Ты — Risk Manager инвесткомитета с правом вето. Ты не оцениваешь идею —
ты защищаешь пользователя от неприемлемого риска. Результаты жёстких проверок кода даны
тебе как факт. Вето — только с конкретной причиной в одно предложение. По-русски."""


def hard_checks(ctx: CouncilContext, proposal: Proposal) -> list[str]:
    """Детерминированные проверки кодом. Непустой список = безусловное вето."""
    vetoes: list[str] = []
    if (proposal.action == "buy" and ctx.position_weight_pct is not None
            and ctx.position_weight_pct >= MAX_POSITION_WEIGHT_PP):
        vetoes.append(f"Концентрация: уже {ctx.position_weight_pct}% портфеля "
                      f"(лимит {MAX_POSITION_WEIGHT_PP}%)")
    if ctx.tech is None and proposal.confidence > OVERCONFIDENCE_THRESHOLD:
        vetoes.append("Переуверенность на тонких данных: нет техники, "
                      f"а confidence {round(proposal.confidence*100)}%")
    return vetoes


def build_risk_user(ctx: CouncilContext, proposal: Proposal, vetoes: list[str]) -> str:
    parts = [f"Тикер: {ctx.ticker}",
             f"Предложение PM: {proposal.action} ({proposal.stance}, "
             f"{round(proposal.confidence*100)}%)",
             f"Тезис: {proposal.thesis}",
             f"Инвалидация: {proposal.invalidation}",
             f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}"]
    if ctx.position_note:
        parts.append(ctx.position_note)
    parts.append("Жёсткие проверки кода: " + ("; ".join(vetoes) if vetoes else "пройдены"))
    return "\n".join(parts)


async def run_risk(llm, ctx: CouncilContext, proposal: Proposal,
                   vetoes: list[str]) -> RiskReview:
    llm_review: RiskReview = await llm.parse(
        model=RISK_MODEL, operation="council_risk",
        messages=[{"role": "system", "content": RISK_SYSTEM},
                  {"role": "user", "content": build_risk_user(ctx, proposal, vetoes)}],
        schema=RiskReview)
    if vetoes:  # hard-вето кода не переспоришь
        return RiskReview(approved=False, veto_reason="; ".join(vetoes),
                          notes=llm_review.notes)
    return llm_review
