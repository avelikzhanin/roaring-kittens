from roaring_kittens.telegram.handlers.ask import (
    QUESTION_PRESETS,
    build_question_keyboard,
    build_ticker_keyboard,
)


def _all_buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_ticker_keyboard_callback_data_and_chunking():
    tickers = ["SBER", "GAZP", "LKOH", "YDEX", "T", "OZON"]
    kb = build_ticker_keyboard(tickers)
    buttons = _all_buttons(kb)
    assert [b.text for b in buttons] == tickers
    assert buttons[0].callback_data == "ask:SBER"
    # 4 в ряд: 6 тикеров -> ряды по 4 и 2
    assert [len(row) for row in kb.inline_keyboard] == [4, 2]


def test_ticker_keyboard_caps_at_12():
    kb = build_ticker_keyboard([f"T{i}" for i in range(20)])
    assert len(_all_buttons(kb)) == 12


def test_question_keyboard_has_presets_for_ticker():
    kb = build_question_keyboard("SBER")
    datas = [b.callback_data for b in _all_buttons(kb)]
    assert datas == ["askq:SBER:full", "askq:SBER:buy", "askq:SBER:sell"]


def test_presets_full_has_no_question_buy_sell_do():
    assert QUESTION_PRESETS["full"][1] is None
    assert "покупать" in QUESTION_PRESETS["buy"][1]
    assert "продавать" in QUESTION_PRESETS["sell"][1]
