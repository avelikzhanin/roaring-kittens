from roaring_kittens.news.matching import match_tickers

ALIAS_MAP = {
    "SBER": frozenset({"сбер банк", "сбербанк", "sber"}),
    "GAZP": frozenset({"газпром", "gazp"}),
    "T": frozenset({"т-банк", "тинькофф", "t"}),
}


def test_matches_by_alias_case_insensitive():
    assert match_tickers("СБЕРБАНК отчитался о прибыли", ALIAS_MAP) == ["SBER"]


def test_matches_multiple():
    text = "Газпром и Сбербанк договорились о сотрудничестве"
    assert match_tickers(text, ALIAS_MAP) == ["GAZP", "SBER"]


def test_short_alias_requires_word_boundary():
    # 't' не должен матчиться внутри слова "отчитался"
    assert match_tickers("Компания отчиталась", ALIAS_MAP) == []
    assert match_tickers("Т-Банк показал рост", ALIAS_MAP) == ["T"]


def test_no_match():
    assert match_tickers("Погода в Москве", ALIAS_MAP) == []


AMBIG_MAP = {
    "PLZL": frozenset({"полюс", "plzl"}),
    "MGNT": frozenset({"магнит", "mgnt"}),
    "OZON": frozenset({"озон", "ozon"}),
}


def test_ambiguous_alias_does_not_false_match_inside_words():
    # длинные, но неоднозначные алиасы не должны ловить обычные слова
    assert match_tickers("Сегодня сильная магнитная буря", AMBIG_MAP) == []
    assert match_tickers("Полюсное сияние над Норильском", AMBIG_MAP) == []
    assert match_tickers("Озоновый слой восстанавливается", AMBIG_MAP) == []


def test_ambiguous_alias_still_matches_on_word_boundary():
    assert match_tickers("Магнит отчитался о прибыли", AMBIG_MAP) == ["MGNT"]
    assert match_tickers("Полюс нарастил добычу золота", AMBIG_MAP) == ["PLZL"]
