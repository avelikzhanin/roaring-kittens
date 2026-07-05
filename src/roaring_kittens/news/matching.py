import re

# Алиасы, совпадающие с обычными русскими словами: даже будучи длинными (>=4),
# они должны матчиться ТОЛЬКО по границе слова, иначе ловят мусор
# ("магнит" -> "магнитная буря", "полюс" -> "полюсное сияние", "озон" -> "озоновый слой").
AMBIGUOUS_ALIASES: frozenset[str] = frozenset({"полюс", "магнит", "озон", "флот", "лента"})


def match_tickers(text: str, alias_map: dict[str, frozenset[str]],
                  ambiguous: frozenset[str] = AMBIGUOUS_ALIASES) -> list[str]:
    """Матч новости на тикеры по алиасам.

    Алиасы длиной >=4 — substring-матч, КРОМЕ неоднозначных (см. AMBIGUOUS_ALIASES)
    и коротких (<4): они матчатся только по границе слова.
    """
    t = text.lower()
    matched = set()
    for ticker, aliases in alias_map.items():
        for alias in aliases:
            a = alias.strip().lower()
            if not a:
                continue
            if len(a) >= 4 and a not in ambiguous:
                if a in t:
                    matched.add(ticker)
                    break
            else:
                if re.search(rf"(?<![a-zа-яё0-9]){re.escape(a)}(?![a-zа-яё0-9])", t):
                    matched.add(ticker)
                    break
    return sorted(matched)
