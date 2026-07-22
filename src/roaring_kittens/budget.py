"""Бюджет-гейт: 80% лимита -> эконом-модели, 100% -> блок тяжёлых циклов."""
from decimal import Decimal

from roaring_kittens.db.users import get_user, month_spend

ECONOM_THRESHOLD = Decimal("0.8")

HEAVY_BLOCKED_MSG = ("💸 Месячный AI-бюджет исчерпан — тяжёлые разборы (комитет) "
                     "заблокированы до 1-го числа. Алерты и лёгкий /ask работают. "
                     "/budget — детали.")


def classify_spend(spent: Decimal, limit: Decimal) -> str:
    if limit <= 0 or spent >= limit:
        return "blocked"
    if spent >= limit * ECONOM_THRESHOLD:
        return "econom"
    return "ok"


async def budget_state(deps, telegram_id: int) -> tuple[str, Decimal, Decimal]:
    """('ok'|'econom'|'blocked', spent, limit). Неизвестный юзер -> blocked."""
    async with deps.session_factory() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            return "blocked", Decimal("0"), Decimal("0")
        spent = await month_spend(session, telegram_id)
    return classify_spend(spent, user.monthly_budget_usd), spent, user.monthly_budget_usd
