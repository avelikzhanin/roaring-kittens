import re


def match_tickers(text: str, alias_map: dict[str, frozenset[str]]) -> list[str]:
    """Алиасы длиной >=4 — substring-матч; короткие — только по границе слова."""
    t = text.lower()
    matched = set()
    for ticker, aliases in alias_map.items():
        for alias in aliases:
            a = alias.strip().lower()
            if not a:
                continue
            if len(a) >= 4:
                if a in t:
                    matched.add(ticker)
                    break
            else:
                if re.search(rf"(?<![a-zа-яё0-9]){re.escape(a)}(?![a-zа-яё0-9])", t):
                    matched.add(ticker)
                    break
    return sorted(matched)
