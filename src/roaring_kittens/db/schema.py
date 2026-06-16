from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()


def _find_schema_sql() -> Path:
    """Ищет db/schema.sql и в editable-, и в installed-layout (CWD=/app в Docker)."""
    here = Path(__file__).resolve()
    candidates = []
    if len(here.parents) > 3:
        candidates.append(here.parents[3] / "db" / "schema.sql")  # editable: /app/db
    candidates.append(Path.cwd() / "db" / "schema.sql")            # installed: CWD/db
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"db/schema.sql not found in {candidates}")


async def ensure_schema(engine: AsyncEngine) -> None:
    """Применяет идемпотентную схему при старте (CREATE ... IF NOT EXISTS).

    Выполняем по одному стейтменту: asyncpg запрещает несколько команд в одном
    prepared-statement, а dollar-quoting в схеме не используется, поэтому split(';') безопасен.
    """
    sql = _find_schema_sql().read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.exec_driver_sql(stmt)
    log.info("schema_ensured", statements=len(statements))
