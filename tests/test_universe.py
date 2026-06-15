import httpx

from roaring_kittens.universe.universe import Instrument, Universe, parse_iss_tickers

ISS_SAMPLE = {
    "analytics": {
        "columns": ["indexid", "tradedate", "ticker", "shortnames", "weight"],
        "data": [
            ["IMOEX", "2026-06-11", "SBER", "Сбербанк", 14.2],
            ["IMOEX", "2026-06-11", "GAZP", "Газпром", 9.1],
        ],
    }
}


def test_parse_iss_tickers():
    assert parse_iss_tickers(ISS_SAMPLE) == ["SBER", "GAZP"]


async def test_universe_load_maps_figi_and_builds_aliases():
    def iss_handler(request):
        return httpx.Response(200, json=ISS_SAMPLE)

    transport = httpx.MockTransport(iss_handler)

    class FakeBroker:
        async def list_shares(self):
            return {"SBER": ("BBG004730N88", "Сбер Банк"), "GAZP": ("BBG004730RP0", "Газпром"),
                    "AAAA": ("BBGX", "Не из индекса")}

    uni = Universe(broker=FakeBroker(), transport=transport)
    await uni.load()
    assert set(uni.tickers()) == {"SBER", "GAZP"}
    sber = uni.get("SBER")
    assert isinstance(sber, Instrument) and sber.figi == "BBG004730N88"
    assert "сбербанк" in sber.aliases          # из EXTRA_ALIASES
    assert "сбер банк" in sber.aliases          # из имени инструмента
    assert uni.resolve("сбер банк") == sber     # резолв по алиасу
    assert uni.resolve("SBER") == sber          # резолв по тикеру
    assert uni.resolve("nope") is None
