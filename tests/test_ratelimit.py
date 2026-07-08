from roaring_kittens.utils.ratelimit import DailyLimiter


def test_allows_up_to_limit():
    limiter = DailyLimiter(limit=3)
    assert [limiter.allow(1) for _ in range(4)] == [True, True, True, False]


def test_limits_are_per_user():
    limiter = DailyLimiter(limit=1)
    assert limiter.allow(1) is True
    assert limiter.allow(2) is True   # другой пользователь — свой счётчик
    assert limiter.allow(1) is False
