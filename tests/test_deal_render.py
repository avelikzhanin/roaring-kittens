from decimal import Decimal

from roaring_kittens.deals_service import build_idea_text
from roaring_kittens.sizing import SizedSuggestion


def test_idea_text_has_levels_size_and_disclaimer():
    s = SizedSuggestion(qty=50, lots=5, cost=Decimal("13100"),
                        risk_rub=Decimal("850"), over_risk=False)
    text = build_idea_text(
        deal_no=12, ticker="SBER", entry=Decimal("262"),
        target=Decimal("290"), exit_price=Decimal("245"),
        exit_note="отменят дивиденды", rationale="Отчёт лучше ожиданий.",
        confidence=0.72, sized=s)
    assert "№12" in text and "SBER" in text and "262" in text
    assert "290" in text and "245" in text
    assert "Продаём если" in text and "отменят дивиденды" in text
    assert "5 лотов (50 шт" in text and "13100" in text
    assert "<i>Не является индивидуальной инвестиционной рекомендацией.</i>" in text
    assert "_" not in text   # HTML parse mode: markdown-курсив запрещён


def test_idea_text_flags_over_risk_and_no_size():
    s = SizedSuggestion(qty=10, lots=1, cost=Decimal("2620"),
                        risk_rub=Decimal("170"), over_risk=True)
    text = build_idea_text(deal_no=1, ticker="SBER", entry=Decimal("262"),
                           target=Decimal("290"), exit_price=Decimal("245"),
                           exit_note="x", rationale="r", confidence=0.6, sized=s)
    assert "выше нормы" in text          # честная приписка про риск
    text2 = build_idea_text(deal_no=2, ticker="SBER", entry=Decimal("262"),
                            target=Decimal("290"), exit_price=Decimal("245"),
                            exit_note="x", rationale="r", confidence=0.6,
                            sized=None)  # сайзинг не посчитался — без блока размера
    assert "лот" not in text2
