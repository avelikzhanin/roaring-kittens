from dataclasses import dataclass, field

import httpx
import structlog

from roaring_kittens.universe.seed import EXTRA_ALIASES, SEED_TICKERS

log = structlog.get_logger()

ISS_URL = "https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/IMOEX.json?limit=100"


def parse_iss_tickers(payload: dict) -> list[str]:
    block = payload["analytics"]
    idx = block["columns"].index("ticker")
    return [row[idx] for row in block["data"]]


@dataclass(frozen=True)
class Instrument:
    ticker: str
    figi: str
    name: str
    aliases: frozenset[str] = field(default_factory=frozenset)


class Universe:
    def __init__(self, broker, transport: httpx.BaseTransport | None = None):
        self._broker = broker
        self._transport = transport
        self._by_ticker: dict[str, Instrument] = {}
        self._alias_index: dict[str, str] = {}  # alias -> ticker

    async def load(self) -> None:
        tickers = await self._fetch_index_tickers()
        shares = await self._broker.list_shares()  # ticker -> (figi, name)
        for t in tickers:
            if t not in shares:
                log.warning("universe_ticker_not_in_tinkoff", ticker=t)
                continue
            figi, name = shares[t]
            aliases = {name.lower(), t.lower()} | set(EXTRA_ALIASES.get(t, []))
            self._by_ticker[t] = Instrument(t, figi, name, frozenset(aliases))
            for a in aliases:
                self._alias_index[a] = t
        log.info("universe_loaded", count=len(self._by_ticker))

    async def _fetch_index_tickers(self) -> list[str]:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
                resp = await client.get(ISS_URL)
                resp.raise_for_status()
                return parse_iss_tickers(resp.json())
        except Exception as exc:
            log.warning("iss_unavailable_using_seed", error=str(exc))
            return list(SEED_TICKERS)

    def tickers(self) -> list[str]:
        return list(self._by_ticker)

    def get(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker.upper())

    def resolve(self, query: str) -> Instrument | None:
        q = query.strip().lower()
        direct = self._by_ticker.get(query.strip().upper())
        if direct:
            return direct
        t = self._alias_index.get(q)
        return self._by_ticker.get(t) if t else None

    def alias_map(self) -> dict[str, frozenset[str]]:
        """ticker -> aliases, для news matching."""
        return {t: i.aliases for t, i in self._by_ticker.items()}
