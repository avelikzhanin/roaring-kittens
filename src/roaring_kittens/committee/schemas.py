from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["bullish", "bearish", "neutral"]


class SpecialistView(BaseModel):
    role: Literal["news", "technical", "fundamentals", "sentiment"]
    stance: Stance
    summary: str = Field(description="2-3 предложения: главный вывод по своей зоне")
    key_points: list[str] = Field(description="2-4 факта из предоставленных данных")
    confidence: float = Field(ge=0, le=1)


class DebateTurn(BaseModel):
    argument: str = Field(description="главный аргумент этого хода, 2-4 предложения")
    rebuttal_of: str = Field(description="какой тезис оппонента атакуешь (кратко)")
    position_after: Stance = Field(description="твоя позиция после этого хода")


class Proposal(BaseModel):
    action: Literal["buy", "sell", "hold", "wait"]
    stance: Stance
    rationale: str = Field(description="3-5 предложений: решение и почему")
    thesis: str = Field(description="однострочный тезис ставки")
    invalidation: str = Field(description="конкретный триггер, при котором тезис ломается")
    confidence: float = Field(ge=0, le=1)


class RiskReview(BaseModel):
    approved: bool
    veto_reason: str | None = None
    notes: list[str] = Field(default_factory=list, description="1-3 замечания по рискам")
