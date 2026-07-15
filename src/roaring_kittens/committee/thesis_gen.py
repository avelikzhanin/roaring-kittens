"""Авто-тезис для позиции без тезиса (position-sync). Дешёвый одиночный вызов."""
from pydantic import BaseModel, Field

from roaring_kittens.committee.context import CouncilContext

THESIS_MODEL = "gpt-4o"

THESIS_SYSTEM = """Ты — аналитик. У пользователя уже ЕСТЬ эта бумага в портфеле.
Сформулируй наиболее правдоподобный ТЕЗИС удержания позиции (зачем её держать)
и КОНКРЕТНЫЙ проверяемый триггер инвалидации (при каком событии/уровне тезис ломается).
Опирайся только на данные. По-русски, кратко."""


class ThesisDraft(BaseModel):
    thesis: str = Field(description="однострочный тезис удержания")
    invalidation: str = Field(description="конкретный проверяемый триггер поломки тезиса")
    confidence: float = Field(ge=0, le=1)


async def run_thesis_draft(llm, ctx: CouncilContext) -> ThesisDraft:
    user = (f"Тикер: {ctx.ticker}\n"
            f"Техника: {ctx.tech.as_text() if ctx.tech else 'данных недостаточно'}\n"
            f"{ctx.dividend_summary}\n"
            f"{ctx.position_note or ''}")
    return await llm.parse(model=THESIS_MODEL, operation="thesis_draft",
                           messages=[{"role": "system", "content": THESIS_SYSTEM},
                                     {"role": "user", "content": user}],
                           schema=ThesisDraft)
