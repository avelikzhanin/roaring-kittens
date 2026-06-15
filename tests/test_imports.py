import importlib


def test_entrypoint_and_scheduler_import():
    """Smoke: untested wiring (main, scheduler, handlers) импортируется без ошибок."""
    importlib.import_module("roaring_kittens.main")
    importlib.import_module("roaring_kittens.scheduler")
    from roaring_kittens.telegram.handlers import all_routers
    assert all_routers is not None
