"""Память комитета: похожие прошлые разборы (с исходом) + применимые уроки."""
import structlog

from roaring_kittens.db.calls import find_similar_calls
from roaring_kittens.db.insights import bump_times_applied, top_insights_by_similarity

log = structlog.get_logger()

MEMORY_CHAR_CAP = 4000  # ~1000-1500 токенов


async def build_memory_note(deps, ticker: str, situation_text: str, *,
                            asked_by: int | None = None) -> str | None:
    """asked_by скоупит похожие разборы: council-summary (=PM rationale) видел
    позицию инициатора — в чужие промпты его нельзя."""
    try:
        emb = await deps.embedder.embed(f"{ticker}: {situation_text}",
                                        operation="memory_query")
    except Exception as exc:
        log.warning("memory_embed_failed", error=str(exc))
        return None
    async with deps.session_factory() as session:
        similar = await find_similar_calls(session, emb, k=3, asked_by=asked_by)
        applicable = await top_insights_by_similarity(session, emb, k=3,
                                                      min_confidence=0.5)
        if applicable:
            await bump_times_applied(session, [i.id for i in applicable])
            await session.commit()
    if not similar and not applicable:
        return None
    lines = ["Память бота (прошлый опыт, учитывай критично):"]
    if similar:
        lines.append("Похожие прошлые разборы:")
        for s in similar:
            outcome = ""
            if s.score_20d:
                sign = "+" if s.score_20d.excess_pp >= 0 else "−"
                outcome = (f" → 20д: {sign}{abs(s.score_20d.excess_pp)} пп vs IMOEX "
                           f"({s.score_20d.verdict})")
            lines.append(f"- {s.created_at:%d.%m} {s.ticker} {s.stance}: "
                         f"{s.summary}{outcome}")
    if applicable:
        lines.append("Выученные уроки:")
        for i in applicable:
            lines.append(f"- {i.summary} (уверенность {round(i.confidence*100)}%)")
    return "\n".join(lines)[:MEMORY_CHAR_CAP]
