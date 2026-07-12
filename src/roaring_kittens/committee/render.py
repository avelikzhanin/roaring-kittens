from roaring_kittens.committee.schemas import Proposal, RiskReview, SpecialistView
from roaring_kittens.telegram.formatting import STANCE_EMOJI

ACTION_RU = {"buy": "покупать", "sell": "продавать", "hold": "держать", "wait": "ждать"}
ROLE_ICON = {"news": "📰", "technical": "📈", "fundamentals": "💰", "sentiment": "🗣"}


def format_council_verdict(ticker: str, views: list[SpecialistView], debate: list[dict],
                           proposal: Proposal, risk: RiskReview) -> str:
    rounds = sum(1 for t in debate if t["speaker"] == "bear")
    votes = " · ".join(f"{ROLE_ICON[v.role]} {STANCE_EMOJI[v.stance]}" for v in views)
    risk_line = "🛡 Risk: ✅ одобрено" if risk.approved \
        else f"🛡 Risk: ⛔️ ВЕТО — {risk.veto_reason}"
    lines = [
        f"🏛 <b>Комитет по {ticker}</b> — {STANCE_EMOJI[proposal.stance]} "
        f"<b>{ACTION_RU[proposal.action]}</b> "
        f"(уверенность {round(proposal.confidence * 100)}%)",
        "",
        proposal.rationale,
        "",
        f"🎯 Тезис: {proposal.thesis}",
        f"🚨 Инвалидация: {proposal.invalidation}",
        "",
        f"Голоса: {votes} · дебаты: {rounds} раунд(а)",
        risk_line,
        "",
        "<i>Это аналитический разбор, не инвестрекомендация.</i>",
    ]
    return "\n".join(lines)


def format_council_protocol(views: list[SpecialistView], debate: list[dict],
                            proposal: Proposal, risk: RiskReview) -> list[str]:
    lines = ["📜 <b>Протокол комитета</b>", ""]
    for v in views:
        lines.append(f"{ROLE_ICON[v.role]} <b>{v.role}</b> — {STANCE_EMOJI[v.stance]} "
                     f"{v.stance} ({round(v.confidence*100)}%)")
        lines.append(v.summary)
        lines += [f"• {p}" for p in v.key_points]
        lines.append("")
    lines.append("⚔️ <b>Дебаты:</b>")
    for t in debate:
        who = "🐂 БЫК" if t["speaker"] == "bull" else "🐻 МЕДВЕДЬ"
        lines.append(f"{who} (→ {t['position_after']}): {t['argument']}")
    lines.append("")
    lines.append(f"👔 <b>PM:</b> {proposal.rationale}")
    if risk.notes:
        lines.append("🛡 Risk-заметки: " + "; ".join(risk.notes))
    return chunk_lines(lines)


def chunk_lines(lines: list[str], limit: int = 3500) -> list[str]:
    chunks, cur = [], ""

    def push(segment: str) -> None:
        nonlocal cur
        if cur and len(cur) + len(segment) + 1 > limit:
            chunks.append(cur)
            cur = segment
        else:
            cur = f"{cur}\n{segment}" if cur else segment

    for line in lines:
        while len(line) > limit:  # одна сверхдлинная строка не должна пробить лимит TG
            push(line[:limit])
            line = line[limit:]
        push(line)
    if cur:
        chunks.append(cur)
    return chunks
