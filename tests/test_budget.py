from decimal import Decimal
from types import SimpleNamespace

import roaring_kittens.budget as budget_mod
from roaring_kittens.budget import budget_state, classify_spend


def test_classify_spend_thresholds():
    limit = Decimal("20")
    assert classify_spend(Decimal("0"), limit) == "ok"
    assert classify_spend(Decimal("15.99"), limit) == "ok"
    assert classify_spend(Decimal("16"), limit) == "econom"     # >= 80%
    assert classify_spend(Decimal("19.99"), limit) == "econom"
    assert classify_spend(Decimal("20"), limit) == "blocked"    # >= 100%
    assert classify_spend(Decimal("5"), Decimal("0")) == "blocked"  # нулевой лимит


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_budget_state_reads_user_and_spend(monkeypatch):
    async def fake_get_user(session, tg_id):
        return SimpleNamespace(monthly_budget_usd=Decimal("20"))

    async def fake_spend(session, tg_id):
        return Decimal("17")

    monkeypatch.setattr(budget_mod, "get_user", fake_get_user)
    monkeypatch.setattr(budget_mod, "month_spend", fake_spend)
    deps = SimpleNamespace(session_factory=lambda: FakeSession())
    state, spent, limit = await budget_state(deps, 111)
    assert state == "econom" and spent == Decimal("17") and limit == Decimal("20")


async def test_budget_state_unknown_user_is_blocked(monkeypatch):
    async def fake_get_user(session, tg_id):
        return None

    monkeypatch.setattr(budget_mod, "get_user", fake_get_user)
    deps = SimpleNamespace(session_factory=lambda: FakeSession())
    assert await budget_state(deps, 999) == ("blocked", Decimal("0"), Decimal("0"))
