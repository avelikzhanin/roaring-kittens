from roaring_kittens.telegram.handlers.ask import build_ticker_keyboard


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
