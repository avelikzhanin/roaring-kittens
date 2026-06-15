"""Phase 0 gate: проверка связности с Tinkoff Invest API.
Запуск: python scripts/smoke_tinkoff.py (нужен env TINKOFF_TOKEN)."""
import asyncio
import os

from tinkoff.invest import AsyncClient


async def main() -> None:
    token = os.environ["TINKOFF_TOKEN"]
    async with AsyncClient(token) as client:
        accounts = await client.users.get_accounts()
        print(f"SMOKE OK: {len(accounts.accounts)} account(s) visible")
        for acc in accounts.accounts:
            print(f"  - id={acc.id} name={acc.name!r}")


if __name__ == "__main__":
    asyncio.run(main())
