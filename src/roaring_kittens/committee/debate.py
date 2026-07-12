from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import DebateTurn, SpecialistView

DEBATE_MODEL = "o4-mini"
MAX_ROUNDS = 3

BULL_SYSTEM = """Ты — Bull Researcher инвесткомитета. Твоя работа — построить СИЛЬНЕЙШИЙ
аргумент ЗА покупку/удержание, даже если данные неоднозначны. Не уклоняйся в нейтральность —
взвешивать будет Portfolio Manager. Атакуй конкретные тезисы оппонента. Опирайся только на
данные комитета, не выдумывай. Если после дебатов честно признаёшь правоту оппонента —
можешь сменить position_after. По-русски, кратко."""

BEAR_SYSTEM = """Ты — Bear Researcher инвесткомитета. Твоя работа — найти риски и построить
СИЛЬНЕЙШИЙ аргумент ПРОТИВ, даже если данные неоднозначны. Не уклоняйся в нейтральность —
взвешивать будет Portfolio Manager. Атакуй конкретные тезисы оппонента. Опирайся только на
данные комитета, не выдумывай. Если после дебатов честно признаёшь правоту оппонента —
можешь сменить position_after. По-русски, кратко."""


def build_debate_user(ctx: CouncilContext, views: list[SpecialistView],
                      debate_log: list[dict], speaker: str) -> str:
    parts = [f"Тикер: {ctx.ticker}", "", "Мнения специалистов:"]
    for v in views:
        parts.append(f"- {v.role} ({v.stance}, {round(v.confidence*100)}%): {v.summary}")
    if ctx.position_note:
        parts.append(f"\n{ctx.position_note}")
    if ctx.prev_call_note:
        parts.append(ctx.prev_call_note)
    if debate_log:
        parts.append("\nХод дебатов:")
        for t in debate_log:
            who = "БЫК" if t["speaker"] == "bull" else "МЕДВЕДЬ"
            parts.append(f"[{who} → {t['position_after']}] {t['argument']}")
    parts.append(f"\nТвой ход ({'бык' if speaker == 'bull' else 'медведь'}).")
    return "\n".join(parts)


async def run_debate_turn(llm, ctx: CouncilContext, views: list[SpecialistView],
                          debate_log: list[dict], speaker: str) -> DebateTurn:
    system = BULL_SYSTEM if speaker == "bull" else BEAR_SYSTEM
    return await llm.parse(
        model=DEBATE_MODEL, operation=f"council_debate_{speaker}",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": build_debate_user(ctx, views, debate_log, speaker)}],
        schema=DebateTurn)


def is_converged(debate_log: list[dict]) -> bool:
    """Сошлись, если последние позиции быка и медведя совпали."""
    last = {}
    for t in debate_log:
        last[t["speaker"]] = t["position_after"]
    return len(last) == 2 and last["bull"] == last["bear"]
