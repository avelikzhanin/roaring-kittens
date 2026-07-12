import asyncio

from roaring_kittens.committee.context import CouncilContext
from roaring_kittens.committee.schemas import SpecialistView
from roaring_kittens.news.models import NewsItem

SPECIALIST_MODEL = "gpt-4o"

_COMMON = """Ты — узкий специалист инвесткомитета по Мосбирже. Отвечай ТОЛЬКО по своей зоне.
Опирайся ТОЛЬКО на предоставленные данные; не выдумывай числа и события.
Если данных мало — честно скажи и ставь низкую confidence. Пиши по-русски, кратко."""

ROLE_PROMPTS: dict[str, str] = {
    "news": _COMMON + "\nТвоя зона: корпоративные и рыночные СОБЫТИЯ (факты из новостей).",
    "technical": _COMMON + "\nТвоя зона: цена, тренд, уровни, индикаторы (числа даны кодом).",
    "fundamentals": _COMMON + "\nТвоя зона: дивиденды и фундаментальная привлекательность.",
    "sentiment": _COMMON + "\nТвоя зона: настроения розничной толпы (посты Smart-Lab); "
                           "учитывай контрарианскую логику: эйфория толпы — тревожный знак.",
}


def _news_block(items: list[NewsItem], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(f"- [{n.published_at:%d.%m}] {n.headline}" for n in items[:10])


def build_specialist_user(ctx: CouncilContext, role: str) -> str:
    tech_text = ctx.tech.as_text() if ctx.tech else "Технических данных недостаточно."
    base = f"Тикер: {ctx.ticker}\nТехника: {tech_text}\n"
    if role == "news":
        return base + "\nНовости (7 дней):\n" + _news_block(ctx.news_facts, "Свежих новостей нет.")
    if role == "technical":
        return base + f"\nИндикаторы: {ctx.indicators.as_text(ctx.tech.last_close if ctx.tech else None)}"
    if role == "fundamentals":
        return base + f"\n{ctx.dividend_summary}"
    return base + "\nПосты Smart-Lab (7 дней):\n" + _news_block(ctx.crowd_posts, "Постов нет.")


async def run_specialist(llm, ctx: CouncilContext, role: str) -> SpecialistView:
    view = await llm.parse(
        model=SPECIALIST_MODEL, operation=f"council_{role}",
        messages=[{"role": "system", "content": ROLE_PROMPTS[role]},
                  {"role": "user", "content": build_specialist_user(ctx, role)}],
        schema=SpecialistView)
    return view.model_copy(update={"role": role})  # роль фиксируем кодом, не доверяем LLM


async def run_specialists(llm, ctx: CouncilContext) -> list[SpecialistView]:
    return list(await asyncio.gather(*(run_specialist(llm, ctx, r) for r in ROLE_PROMPTS)))
