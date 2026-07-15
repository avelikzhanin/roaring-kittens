from datetime import datetime, timezone
from decimal import Decimal

from roaring_kittens.broker.models import PortfolioSnapshot, Position
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.positions_sync import diff_positions


def _pos(ticker, qty="100", cur="100"):
    return Position(ticker=ticker, name=ticker, figi=f"F-{ticker}",
                    quantity=Decimal(qty), avg_price=Decimal("90"),
                    current_price=Decimal(cur), pnl_pct=Decimal("11.1"))


def _thesis(ticker, backed=True):
    return ThesisRecord(id=ticker, ticker=ticker, figi=f"F-{ticker}",
                        opened_at=datetime.now(tz=timezone.utc), closed_at=None,
                        status="active", thesis="t", invalidation="i", source="auto",
                        confidence=0.5, entry_price=None, realized_return_pct=None,
                        close_reason=None, backed_by_position=backed)


def test_diff_detects_closures_new_positions_and_backing():
    # Портфель 100k: SBER 60k (60%), LKOH 40k (40%).
    snap = PortfolioSnapshot(total_value=Decimal("100000"),
                             positions=[_pos("SBER", qty="600"),
                                        _pos("LKOH", qty="400")])
    active = [_thesis("GAZP", backed=True),    # позиция продана — закрыть с результатом
              _thesis("OZON", backed=False),   # ИДЕЯ по некупленной бумаге — НЕ трогать
              _thesis("SBER", backed=False)]   # идея, а бумага теперь куплена — пометить backed
    actions = diff_positions(snap, active, suppressed=set())
    assert [t.ticker for t in actions.to_close] == ["GAZP"]
    assert [p.ticker for p in actions.to_draft] == ["LKOH"]  # ≥5% и без тезиса
    assert [t.ticker for t in actions.to_back] == ["SBER"]   # идея стала позицией


def test_diff_respects_suppressed_and_small_positions():
    snap = PortfolioSnapshot(total_value=Decimal("100000"),
                             positions=[_pos("SBER", qty="600"),
                                        _pos("PLZL", qty="1")])   # 100/100k = 0.1%
    actions = diff_positions(snap, [], suppressed={"SBER"})       # владелец удалял тезис
    assert actions.to_draft == [] and actions.to_close == [] and actions.to_back == []
    empty = PortfolioSnapshot(total_value=Decimal("0"), positions=[])
    actions = diff_positions(empty, [_thesis("SBER", backed=True)], suppressed=set())
    assert [t.ticker for t in actions.to_close] == ["SBER"]
