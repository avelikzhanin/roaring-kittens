from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DB, requires_db

from roaring_kittens.db.schema import ensure_schema

pytestmark = requires_db


async def test_ensure_schema_creates_tables_idempotently():
    engine = create_async_engine(TEST_DB)
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
