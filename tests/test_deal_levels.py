from decimal import Decimal

from roaring_kittens.deals_service import sanitize_levels


def test_levels_pass_through_when_sane():
    t, e = sanitize_levels(entry=Decimal("262"), target=290.0, exit_price=245.0)
    assert (t, e) == (Decimal("290"), Decimal("245"))


def test_levels_fallback_when_missing_or_insane():
    # нет уровней -> -7%/+14% от входа
    t, e = sanitize_levels(entry=Decimal("100"), target=None, exit_price=None)
    assert (t, e) == (Decimal("114"), Decimal("93"))
    # exit выше входа — бред -> фолбэк
    t, e = sanitize_levels(entry=Decimal("100"), target=120.0, exit_price=105.0)
    assert e == Decimal("93")
    # exit слишком далеко (>20%) -> фолбэк
    t, e = sanitize_levels(entry=Decimal("100"), target=120.0, exit_price=60.0)
    assert e == Decimal("93")
    # target ниже входа -> фолбэк target, exit валиден остаётся
    t, e = sanitize_levels(entry=Decimal("100"), target=95.0, exit_price=94.0)
    assert t == Decimal("114") and e == Decimal("94")
