"""Ядро /council: прогон графа + персист. Используется handler'ом и Thesis Validator'ом."""
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable
from uuid import UUID as UUIDType

import structlog

from roaring_kittens.committee.context import CouncilContext, build_council_context
from roaring_kittens.committee.debate import MAX_ROUNDS, is_converged
from roaring_kittens.committee.graph import build_council_graph
from roaring_kittens.committee.schemas import Proposal, RiskReview
from roaring_kittens.db.calls import save_call
from roaring_kittens.db.council import save_council_run
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()

OnStage = Callable[[str], Awaitable[None]]


@dataclass
class CouncilOutcome:
    state: dict
    proposal: Proposal
    risk: RiskReview
    call_id: UUIDType | None
    run_id: UUIDType | None


def next_stage_text(node: str, state: dict, ticker: str) -> str | None:
    """astream(updates) стреляет ПОСЛЕ узла — анонсируем СЛЕДУЮЩУЮ стадию."""
    if node == "specialists":
        return f"⚔️ {ticker}: аналитики высказались — дебаты Bull vs Bear…"
    if node == "bear":
        if state["round"] >= MAX_ROUNDS or is_converged(state["debate"]):
            return f"👔 {ticker}: дебаты завершены — Portfolio Manager взвешивает…"
        return f"⚔️ {ticker}: дебаты, раунд {state['round'] + 1}…"
    if node == "manager":
        return f"🛡 {ticker}: Risk Manager проверяет…"
    return None


async def _persist_council(deps, instrument: Instrument, asked_by: int,
                           ctx: CouncilContext, state: dict):
    """Одобренный вердикт → calls (+embedding); транскрипт (с meta) → council_runs."""
    proposal, risk = state["proposal"], state["risk"]
    call_id = run_id = None
    embedding = None
    try:
        embedding = await deps.embedder.embed(
            f"{instrument.ticker} {proposal.stance}: {proposal.rationale}",
            operation="embed_call")
    except Exception as exc:
        log.warning("embed_call_failed", error=str(exc))
    async with deps.session_factory() as session:
        if risk.approved:
            call_id = await save_call(
                session, asked_by=asked_by, ticker=instrument.ticker,
                figi=instrument.figi, source="council", question=None,
                stance=proposal.stance, confidence=proposal.confidence,
                summary=proposal.rationale,
                price_at_call=ctx.tech.last_close if ctx.tech else None,
                news_urls=[n.url for n in ctx.news_facts + ctx.crowd_posts],
                embedding=embedding)
        held = bool(ctx.position_note) and "НЕТ" not in ctx.position_note
        transcript = {
            "meta": {"ticker": instrument.ticker, "figi": instrument.figi,
                     "price_at_call": str(ctx.tech.last_close) if ctx.tech else None,
                     "held": held},
            "views": [v.model_dump() for v in state["views"]],
            "debate": state["debate"],
            "proposal": proposal.model_dump(),
            "risk": risk.model_dump(),
        }
        run_id = await save_council_run(session, ticker=instrument.ticker,
                                        asked_by=asked_by, transcript=transcript,
                                        call_id=call_id)
        await session.commit()
    return call_id, run_id


async def run_council_flow(deps, instrument: Instrument, asked_by: int,
                           ctx: CouncilContext | None = None,
                           on_stage: OnStage | None = None,
                           broker=None) -> CouncilOutcome:
    if ctx is None:
        ctx = await build_council_context(deps, instrument, asked_by,
                                          today=date.today(), broker=broker)
    graph = build_council_graph(deps.llm)
    state: dict = {"ctx": ctx}
    async for chunk in graph.astream(state, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if on_stage:
                stage = next_stage_text(node, state, instrument.ticker)
                if stage:
                    try:
                        await on_stage(stage)
                    except Exception:
                        pass
    call_id = run_id = None
    try:  # персист не должен ронять ответ
        call_id, run_id = await _persist_council(deps, instrument, asked_by, ctx, state)
    except Exception as exc:
        log.error("council_persist_failed", ticker=instrument.ticker, error=str(exc))
    return CouncilOutcome(state=state, proposal=state["proposal"], risk=state["risk"],
                          call_id=call_id, run_id=run_id)
