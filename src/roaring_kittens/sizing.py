"""Risk-based размер сделки: одна сделка теряет не больше RISK_PCT портфеля.

qty = (RISK_PCT × portfolio) / (entry − exit), вниз до целых лотов;
кап — CONCENTRATION_CAP стоимости портфеля (лимит Risk Manager);
минимум 1 лот (over_risk=True, если 1 лот рискует больше нормы)."""
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

RISK_PCT = Decimal("0.01")            # 1% портфеля на сделку
CONCENTRATION_CAP = Decimal("0.15")   # тот же лимит, что у Risk Manager


@dataclass(frozen=True)
class SizedSuggestion:
    qty: int          # в ШТУКАХ (кратно лоту)
    lots: int
    cost: Decimal     # qty × entry
    risk_rub: Decimal # qty × (entry − exit)
    over_risk: bool   # даже 1 лот рискует больше 1% портфеля


def suggest_qty(*, portfolio_value: Decimal, entry: Decimal,
                exit_price: Decimal, lot: int) -> SizedSuggestion | None:
    per_share_risk = entry - exit_price
    if per_share_risk <= 0 or portfolio_value <= 0 or entry <= 0 or lot < 1:
        return None
    risk_budget = portfolio_value * RISK_PCT
    raw_shares = risk_budget / per_share_risk
    lots = int((raw_shares / lot).to_integral_value(rounding=ROUND_DOWN))
    # кап концентрации
    max_cost = portfolio_value * CONCENTRATION_CAP
    while lots > 0 and lots * lot * entry > max_cost:
        lots -= 1
    over_risk = False
    if lots < 1:
        lots, over_risk = 1, True  # минимум 1 лот, честно флажим риск
    qty = lots * lot
    return SizedSuggestion(qty=qty, lots=lots, cost=qty * entry,
                           risk_rub=qty * per_share_risk, over_risk=over_risk)
