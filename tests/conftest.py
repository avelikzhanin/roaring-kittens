import os
from pathlib import Path

import pytest

# Пример: postgresql+asyncpg://kittens:kittens@localhost:5432/kittens_test
TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def db_session_factory():
    import asyncpg
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    raw = TEST_DB.replace("+asyncpg", "")
    schema = Path(__file__).resolve().parents[1].joinpath("db", "schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(raw)
    await conn.execute(schema)
    await conn.execute("TRUNCATE news_events, usage_log, bot_state")
    await conn.close()

    engine = create_async_engine(TEST_DB)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
