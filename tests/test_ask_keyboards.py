from roaring_kittens.telegram.handlers.ask import (
    EXAMPLE_QUESTIONS,
    build_ticker_keyboard,
    pick_examples,
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


def test_ticker_keyboard_caps_at_12_by_default():
    kb = build_ticker_keyboard([f"T{i}" for i in range(20)])
    assert len(_all_buttons(kb)) == 12


def test_ticker_keyboard_cap_override_shows_all():
    kb = build_ticker_keyboard([f"T{i}" for i in range(46)], cap=46)
    assert len(_all_buttons(kb)) == 46


def test_ticker_keyboard_all_button():
    kb = build_ticker_keyboard(["SBER"], with_all_button=True)
    assert _all_buttons(kb)[-1].callback_data == "ask_all"


def test_pick_examples_uses_pool_and_tickers():
    examples = pick_examples(["SBER", "GAZP"], n=2)
    assert len(examples) == 2
    for e in examples:
        assert e.startswith("/ask SBER ") or e.startswith("/ask GAZP ")
        assert any(e.endswith(q) for q in EXAMPLE_QUESTIONS)


def test_pick_examples_empty_tickers_fallback():
    examples = pick_examples([], n=1)
    assert examples[0].startswith("/ask SBER ")
