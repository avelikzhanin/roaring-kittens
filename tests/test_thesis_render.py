from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from roaring_kittens.db.calls import HistoryItem, ScoredCall
from roaring_kittens.db.insights import InsightRecord
from roaring_kittens.db.theses import ThesisRecord
from roaring_kittens.telegram.handlers.thesis import (
    format_history, format_insights, format_theses,
)

NOW = datetime.now(tz=timezone.utc)


def test_format_theses_lists_active():
    t = ThesisRecord(id=uuid4(), ticker="SBER", figi="F", opened_at=NOW, closed_at=None,
                     status="active", thesis="дивидендная история",
                     invalidation="дивы < 20 ₽", source="auto", confidence=0.6,
                     entry_price=Decimal("280"), realized_return_pct=None,
                     close_reason=None, backed_by_position=True)
    text = format_theses([t])
    # LLM-текст экранируется для HTML parse_mode: "<" -> "&lt;"
    assert "SBER" in text and "дивидендная" in text and "дивы &lt; 20" in text
    assert "идея" not in text  # backed-тезис не помечается идеей


def test_format_theses_empty():
    assert "нет" in format_theses([]).lower()


def test_format_insights():
    i = InsightRecord(id=uuid4(), created_at=NOW, summary="банки под дивы работают",
                      scope="pattern", scope_value="x", confidence=0.8, times_applied=3)
    text = format_insights([i])
    assert "банки под дивы" in text and "80%" in text and "3" in text


def test_format_history_with_scores():
    item = HistoryItem(created_at=NOW, source="council", stance="bullish",
                       confidence=0.7, summary="рост",
                       score_20d=ScoredCall(ticker="SBER", stance="bullish",
                                            created_at=NOW, source="council",
                                            horizon_days=20,
                                            stock_return_pct=Decimal("5"),
                                            imoex_return_pct=Decimal("1"),
                                            verdict="hit"))
    text = format_history("SBER", [item])
    assert "SBER" in text and "hit" in text and "council" in text
