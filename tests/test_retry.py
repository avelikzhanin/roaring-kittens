import pytest

from roaring_kittens.utils.retry import retry_async


async def test_retries_then_succeeds():
    calls = {"n": 0}

    @retry_async(attempts=3, base_delay=0.01)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 3


async def test_raises_after_exhaustion():
    @retry_async(attempts=2, base_delay=0.01)
    async def always_fails():
        raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        await always_fails()
