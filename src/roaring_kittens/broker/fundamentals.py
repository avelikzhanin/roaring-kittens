"""Фундаментал v1 = дивиденды. Все числа считает код — LLM получает готовый текст."""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from roaring_kittens.broker.models import DividendItem


def format_dividend_summary(items: list[DividendItem], last_close: Decimal | None,
                            today: date) -> str:
    dated = sorted([i for i in items if i.payment_date is not None],
                   key=lambda i: i.payment_date)
    paid = [i for i in dated if i.payment_date <= today]
    announced = [i for i in dated if i.payment_date > today]
    if not dated:
        return "Дивиденды за последние 3 года не выплачивались (или данных нет)."
    lines: list[str] = []
    if paid:
        lines.append("Дивиденды (последние выплаты):")
        for i in paid[-4:]:
            lines.append(f"- {i.payment_date:%d.%m.%Y}: {i.amount} ₽")
        year_ago = today - timedelta(days=365)
        last12 = sum((i.amount for i in paid if i.payment_date >= year_ago), Decimal("0"))
        if last12 > 0:
            line = f"Сумма за 12 мес: {last12} ₽"
            if last_close:
                y = (last12 / last_close * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
                line += f" (~{y}% доходности к текущей цене)"
            lines.append(line)
    for i in announced:
        lines.append(f"Объявлено (ещё не выплачено): {i.payment_date:%d.%m.%Y}: {i.amount} ₽")
    return "\n".join(lines)
