from roaring_kittens.telegram.handlers.watchlist import format_watchlist


def test_format_watchlist_lists_tickers():
    text = format_watchlist(["GAZP", "SBER"])
    assert "GAZP" in text and "SBER" in text and "watch" in text.lower()


def test_format_watchlist_empty():
    text = format_watchlist([])
    assert "пуст" in text.lower() and "/watch" in text
