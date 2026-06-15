from types import SimpleNamespace

from roaring_kittens.telegram.middleware import AllowListMiddleware


async def test_allowed_user_passes():
    mw = AllowListMiddleware(allowed_ids={42})
    called = {"v": False}

    async def handler(event, data):
        called["v"] = True
        return "handled"

    data = {"event_from_user": SimpleNamespace(id=42)}
    result = await mw(handler, event=object(), data=data)
    assert result == "handled" and called["v"]


async def test_unknown_user_is_dropped():
    mw = AllowListMiddleware(allowed_ids={42})

    async def handler(event, data):
        raise AssertionError("must not be called")

    data = {"event_from_user": SimpleNamespace(id=999)}
    assert await mw(handler, event=object(), data=data) is None
