from decimal import Decimal

from roaring_kittens.sizing import SizedSuggestion, suggest_qty

PV = Decimal("100000")  # портфель 100к


def test_risk_based_qty_basic():
    # риск 1% = 1000₽; стоп-дистанция 262-245=17₽ -> 58.8 акций -> 5 лотов по 10
    s = suggest_qty(portfolio_value=PV, entry=Decimal("262"),
                    exit_price=Decimal("245"), lot=10)
    assert isinstance(s, SizedSuggestion)
    assert s.qty == 50                      # 58 акций -> вниз до целых лотов
    assert s.cost == Decimal("13100")       # 50 × 262
    assert s.risk_rub == Decimal("850")     # 50 × 17
    assert s.over_risk is False


def test_concentration_cap_15pct():
    # стоп близко -> риск-формула даёт огромный размер; кап 15% портфеля
    s = suggest_qty(portfolio_value=PV, entry=Decimal("100"),
                    exit_price=Decimal("99"), lot=1)
    assert s.cost <= PV * Decimal("0.15")
    assert s.qty == 150                     # 15000₽ / 100₽


def test_tiny_portfolio_min_one_lot_flagged():
    # портфель 900₽: 1% = 9₽ риска, лот SBER стоит 2620₽ -> минимум 1 лот, over_risk
    s = suggest_qty(portfolio_value=Decimal("900"), entry=Decimal("262"),
                    exit_price=Decimal("245"), lot=10)
    assert s.qty == 10 and s.over_risk is True


def test_invalid_levels_return_none():
    assert suggest_qty(portfolio_value=PV, entry=Decimal("100"),
                       exit_price=Decimal("100"), lot=1) is None
    assert suggest_qty(portfolio_value=Decimal("0"), entry=Decimal("100"),
                       exit_price=Decimal("90"), lot=1) is None
