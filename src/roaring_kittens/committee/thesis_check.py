"""Валидация тезиса свежими новостями (gpt-4o-mini, копейки)."""
from typing import Literal

from pydantic import BaseModel, Field

from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.news.models import NewsItem

CHECK_MODEL = "gpt-4o-mini"

CHECK_SYSTEM = """Ты проверяешь, не сломали ли свежие новости инвестиционный тезис.
Отвечай строго по предоставленному. invalidated — только если новость ПРЯМО срабатывает
триггер инвалидации или очевидно рушит тезис. weakened — если новость заметно против
тезиса, но триггер не сработал. Иначе still_valid. По-русски, кратко."""


class ThesisCheck(BaseModel):
    status: Literal["still_valid", "weakened", "invalidated"]
    reasoning_short: str = Field(description="одно предложение почему")


async def run_thesis_check(llm, thesis: ThesisRecord,
                           news: list[NewsItem]) -> ThesisCheck:
    headlines = "\n".join(f"- {n.headline}" for n in news[:8])
    user = (f"Тикер: {thesis.ticker}\n"
            f"Тезис: {thesis.thesis}\n"
            f"Триггер инвалидации: {thesis.invalidation}\n\n"
            f"Свежие новости:\n{headlines}")
    return await llm.parse(model=CHECK_MODEL, operation="thesis_check",
                           messages=[{"role": "system", "content": CHECK_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ThesisCheck)


def decide_validation_action(status: str, council_recent: bool) -> str:
    """invalidated → авто-комитет (но не чаще 1/сутки на тикер); weakened → уведомить."""
    if status == "invalidated":
        return "notify" if council_recent else "council"
    if status == "weakened":
        return "notify"
    return "nothing"
