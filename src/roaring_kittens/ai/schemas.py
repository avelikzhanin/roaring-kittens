from typing import Literal

from pydantic import BaseModel, Field


class AnalystReport(BaseModel):
    """Structured output одиночного аналитика (Фаза 1)."""
    ticker: str
    stance: Literal["bullish", "bearish", "neutral"]
    summary: str = Field(description="2-4 предложения: главный вывод по бумаге сейчас")
    key_points: list[str] = Field(description="3-6 ключевых фактов из данных")
    risks: list[str] = Field(description="1-4 главных риска")
    confidence: float = Field(ge=0, le=1, description="насколько данных достаточно для вывода")
