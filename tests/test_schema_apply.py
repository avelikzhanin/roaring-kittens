import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from roaring_kittens.db.schema import ensure_schema

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_ensure_schema_creates_tables_idempotently():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        # дважды — проверяем идемпотентность (CREATE ... IF NOT EXISTS)
        await ensure_schema(engine)
        await ensure_schema(engine)
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ))
            tables = {r[0] for r in rows}
        assert {"news_events", "usage_log"} <= tables
    finally:
        await engine.dispose()
