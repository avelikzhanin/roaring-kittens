"""Применяет db/schema.sql к базе из DATABASE_URL. Идемпотентно."""
import asyncio
import os
from pathlib import Path

import asyncpg


async def main() -> None:
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    sql = Path(__file__).resolve().parents[1].joinpath("db", "schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(sql)  # asyncpg simple-query: multi-statement OK
        print("SCHEMA OK")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
