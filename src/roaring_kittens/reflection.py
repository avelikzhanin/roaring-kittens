"""Reflective Agent: раз в неделю извлекает уроки из закрытых тезисов и оценённых вызовов."""
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field

from roaring_kittens.ai.usage_context import use_user
from roaring_kittens.db.calls import ScoredCall, get_scored_calls
from roaring_kittens.db.insights import save_insight
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.db.theses import ThesisRecord, get_recently_closed
from roaring_kittens.telegram.formatting import esc

log = structlog.get_logger()

REFLECTION_MODEL = "gpt-4o"

REFLECTION_SYSTEM = """Ты — рефлексивный агент инвест-бота. Перед тобой итоги недели:
закрытые тезисы (с фактическим результатом) и оценённые прошлые разборы (hit/miss vs IMOEX).
Извлеки 0-3 КОНКРЕТНЫХ переиспользуемых урока (что работает/не работает), только если
для них есть основания в данных. Не выдумывай. Каждому уроку — scope
(ticker|sector|pattern|general) и честная confidence. Плюс короткое резюме недели. По-русски."""


class InsightDraft(BaseModel):
    summary: str = Field(description="переиспользуемый урок одной фразой")
    scope: str = Field(description="ticker|sector|pattern|general")
    scope_value: str | None = None
    confidence: float = Field(ge=0, le=1)


class ReflectionOutput(BaseModel):
    weekly_summary: str = Field(description="2-4 предложения: как прошла неделя")
    insights: list[InsightDraft] = Field(default_factory=list)


def build_reflection_user(closed: list[ThesisRecord],
                          scored: list[ScoredCall]) -> str:
    parts = ["Закрытые тезисы за неделю:"]
    if closed:
        for t in closed:
            ret = "n/a" if t.realized_return_pct is None else f"{t.realized_return_pct}%"
            parts.append(f"- {t.ticker} [{t.status}] «{t.thesis}» → {ret} "
                         f"({t.close_reason})")
    else:
        parts.append("(нет)")
    parts.append("\nОценённые разборы за неделю (20д, vs IMOEX):")
    if scored:
        for s in scored:
            parts.append(f"- {s.ticker} {s.stance} → {s.verdict} "
                         f"(бумага {s.stock_return_pct}%, IMOEX {s.imoex_return_pct}%)")
    else:
        parts.append("(нет)")
    return "\n".join(parts)


async def run_reflection(llm, closed: list[ThesisRecord],
                         scored: list[ScoredCall]) -> ReflectionOutput | None:
    if not closed and not scored:
        return None
    return await llm.parse(
        model=REFLECTION_MODEL, operation="weekly_reflection",
        messages=[{"role": "system", "content": REFLECTION_SYSTEM},
                  {"role": "user", "content": build_reflection_user(closed, scored)}],
        schema=ReflectionOutput)


async def weekly_reflection_job(deps, bot) -> None:
    owner_id = await fetch_owner_id(deps.session_factory)
    if owner_id is None:
        return
    week_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
    async with deps.session_factory() as session:
        # admin-scoped (решение 3 плана 4b): уроки — из закрытых тезисов владельца
        closed = await get_recently_closed(session, days=7, owner_id=owner_id)
        scored = [s for s in await get_scored_calls(session)
                  if s.scored_at and s.scored_at >= week_ago
                  and s.horizon_days == 20]  # один горизонт — без дублей
    with use_user(owner_id):
        result = await run_reflection(deps.llm, closed, scored)
    if result is None:
        log.info("reflection_skipped_no_material")
        return
    saved = 0
    for draft in result.insights[:3]:
        embedding = None
        try:
            embedding = await deps.embedder.embed(draft.summary, operation="embed_insight")
        except Exception as exc:
            log.warning("embed_insight_failed", error=str(exc))
        async with deps.session_factory() as session:
            await save_insight(session, summary=draft.summary, scope=draft.scope,
                               scope_value=draft.scope_value,
                               confidence=draft.confidence, embedding=embedding)
            await session.commit()
        saved += 1
    lines = ["📅 <b>Еженедельная рефлексия</b>", "", esc(result.weekly_summary)]
    if result.insights:
        lines += ["", "💡 <b>Новые уроки:</b>"]
        lines += [f"• {esc(d.summary)} ({round(d.confidence*100)}%)"
                  for d in result.insights[:3]]
    lines += ["", "Уроки будут подмешиваться комитету в похожих ситуациях. /insights — все."]
    await bot.send_message(owner_id, "\n".join(lines))
    log.info("reflection_done", insights=saved)
