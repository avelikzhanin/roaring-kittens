from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings


@dataclass
class Deps:
    settings: Settings
    broker: TinkoffBroker
    session_factory: async_sessionmaker[AsyncSession]
    # universe/llm добавятся в Фазе 1 (Task 12/19)
