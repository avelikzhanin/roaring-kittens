from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.schemas import AnalystReport
from roaring_kittens.broker.tech import TechSummary
from roaring_kittens.news.models import NewsItem

ANALYST_MODEL = "gpt-4o"

SYSTEM_PROMPT = """Ты — аналитик российского фондового рынка (Московская биржа).
Твоя задача — дать честный, взвешенный разбор бумаги на основе ТОЛЬКО предоставленных данных.

Правила:
- НЕ выдумывай числа. Все цены и проценты бери из блока «Техника». Если данных нет — так и скажи.
- Новости оценивай критично: пресс-релизы и пересказы — слабый сигнал.
- Это не инвестиционная рекомендация, а аналитический разбор для частного инвестора.
- Пиши по-русски, кратко и по делу."""


def _format_news(news: list[NewsItem]) -> str:
    if not news:
        return "Свежих новостей по бумаге нет."
    lines = []
    for n in news[:15]:
        lines.append(f"- [{n.published_at:%d.%m %H:%M}] {n.headline} ({n.source})")
    return "\n".join(lines)


def build_analyst_messages(ticker: str, tech: TechSummary | None,
                           news: list[NewsItem], question: str | None) -> list[dict]:
    tech_text = tech.as_text() if tech else "Технических данных недостаточно."
    user = (
        f"Тикер: {ticker}\n\n"
        f"Техника:\n{tech_text}\n\n"
        f"Новости (последние):\n{_format_news(news)}\n"
    )
    if question:
        user += f"\nВопрос пользователя: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def run_analyst(llm: LLM, ticker: str, tech: TechSummary | None,
                      news: list[NewsItem], question: str | None) -> AnalystReport:
    messages = build_analyst_messages(ticker, tech, news, question)
    # temperature=0.2: снижаем разброс между повторными разборами одной бумаги
    return await llm.parse(model=ANALYST_MODEL, operation="analyst",
                           messages=messages, schema=AnalystReport, temperature=0.2)
