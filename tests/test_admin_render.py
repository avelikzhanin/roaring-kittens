from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.db.users import UserRecord
from roaring_kittens.telegram.handlers.admin import format_users
from roaring_kittens.telegram.handlers.budget_cmd import format_budget

NOW = datetime.now(tz=timezone.utc)


def _u(tg, role="user", token=True):
    return UserRecord(telegram_id=tg, username=f"u{tg}", role=role, status="active",
                      has_token=token, monthly_budget_usd=Decimal("20"), created_at=NOW)


def test_format_users_shows_roles_and_spend():
    text = format_users([_u(500, role="admin", token=False), _u(111)],
                        {500: Decimal("3.5"), 111: Decimal("17.2")})
    assert "500" in text and "admin" in text
    assert "111" in text and "17.2" in text and "20" in text


def test_format_budget_states():
    assert "🟢" in format_budget("ok", Decimal("2"), Decimal("20"))
    assert "🟡" in format_budget("econom", Decimal("17"), Decimal("20"))
    assert "🔴" in format_budget("blocked", Decimal("20"), Decimal("20"))
