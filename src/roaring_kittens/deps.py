from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from roaring_kittens.ai.llm import LLM
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings
from roaring_kittens.universe.universe import Universe


@dataclass
class Deps:
    settings: Settings
    broker: TinkoffBroker
    session_factory: async_sessionmaker[AsyncSession]
    universe: Universe
    llm: LLM
