"""Классификатор значимости свежих новостей для тикеров без тезиса (портфель/watchlist)."""
from typing import Literal

from pydantic import BaseModel, Field

from roaring_kittens.news.models import NewsItem

IMPACT_MODEL = "gpt-4o-mini"

IMPACT_SYSTEM = """Ты оцениваешь значимость свежих новостей для КОНКРЕТНОЙ акции Мосбиржи.
Категории:
- critical: делистинг, санкции ПРЯМО на компанию, арест активов/менеджмента,
  крупная авария/катастрофа на её объектах, доп.эмиссия с размытием.
- high: решение по дивидендам (особенно vs ожиданий), M&A, отчётность сильно
  лучше/хуже консенсуса, штраф/иск на значимую сумму, смена CEO.
- medium: прогнозы аналитиков по бумаге, операционные результаты, новости сектора
  с прямым влиянием.
- low: обычные корпоративные новости без ценового смысла.
- noise: PR, повторы, общерыночные обзоры, упоминания вскользь.
Общерыночный фон (индекс, настроение рынка, санкции «в целом») — noise.
Сомневаешься между уровнями — бери НИЖНИЙ. По-русски, кратко."""


class ImpactCheck(BaseModel):
    impact: Literal["critical", "high", "medium", "low", "noise"]
    direction: Literal["bullish", "bearish", "ambiguous"]
    reasoning_short: str = Field(description="одно предложение почему")


async def run_impact_check(llm, ticker: str, news: list[NewsItem]) -> ImpactCheck:
    headlines = "\n".join(f"- {n.headline}" for n in news[:8])
    user = f"Тикер: {ticker}\n\nСвежие новости:\n{headlines}"
    return await llm.parse(model=IMPACT_MODEL, operation="impact_check",
                           messages=[{"role": "system", "content": IMPACT_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ImpactCheck)


def decide_impact_action(impact: str, council_recent: bool) -> str:
    """critical — алерт сквозь всё, но комитет с суточным guard'ом (дубли той же
    истории из разных источников не должны гонять комитет повторно);
    high — комитет с guard'ом; medium — алерт."""
    if impact == "critical":
        return "notify_critical" if council_recent else "council_critical"
    if impact == "high":
        return "notify" if council_recent else "council"
    if impact == "medium":
        return "notify"
    return "nothing"
