from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import Proposal, SpecialistView

PM_MODEL = "gpt-4o"

PM_SYSTEM = """Ты — Portfolio Manager инвесткомитета. Ты не бык и не медведь — ты прагматик.
Перед тобой мнения 4 специалистов и протокол дебатов Bull vs Bear. Прими решение в интересах
пользователя. Если уверенности нет — выбирай wait. Если позиции пользователя нет или счёт
пуст — это «режим идей»: action=buy означает идею на покупку, БЕЗ размера позиции.
thesis — одна строка, invalidation — конкретный проверяемый триггер. По-русски, кратко."""


def build_manager_user(ctx: CouncilContext, views: list[SpecialistView],
                       debate_log: list[dict]) -> str:
    parts = [f"Тикер: {ctx.ticker}",
             f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}",
             "", "Мнения специалистов:"]
    for v in views:
        parts.append(f"- {v.role} ({v.stance}, {round(v.confidence*100)}%): {v.summary}")
    parts.append("\nПротокол дебатов:")
    if debate_log:
        for t in debate_log:
            who = "БЫК" if t["speaker"] == "bull" else "МЕДВЕДЬ"
            parts.append(f"[{who} → {t['position_after']}] {t['argument']}")
    else:
        parts.append("(дебатов не было)")
    if ctx.position_note:
        parts.append(f"\n{ctx.position_note}")
    if ctx.prev_call_note:
        parts.append(ctx.prev_call_note)
    if ctx.memory_note:
        parts.append(f"\n{ctx.memory_note}")
    return "\n".join(parts)


async def run_manager(llm, ctx: CouncilContext, views: list[SpecialistView],
                      debate_log: list[dict]) -> Proposal:
    return await llm.parse(
        model=PM_MODEL, operation="council_manager",
        messages=[{"role": "system", "content": PM_SYSTEM},
                  {"role": "user", "content": build_manager_user(ctx, views, debate_log)}],
        schema=Proposal)
