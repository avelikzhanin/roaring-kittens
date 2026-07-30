from roaring_kittens.scanner import ScreenVerdict, pick_best


def _v(ticker, score, attractive=True):
    return ticker, ScreenVerdict(attractive=attractive, score=score,
                                 reason_short="r")


def test_pick_best_takes_highest_above_threshold():
    best = pick_best([_v("SBER", 55), _v("LKOH", 82), _v("GAZP", 74)])
    assert best[0] == "LKOH"


def test_pick_best_none_when_below_threshold_or_unattractive():
    assert pick_best([_v("SBER", 69), _v("GAZP", 50)]) is None
    assert pick_best([_v("SBER", 90, attractive=False)]) is None
    assert pick_best([]) is None
