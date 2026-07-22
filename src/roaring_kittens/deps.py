from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from roaring_kittens.ai.embeddings import Embedder
from roaring_kittens.ai.llm import LLM
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings
from roaring_kittens.universe.universe import Universe
from roaring_kittens.utils.ratelimit import DailyLimiter

GUEST_ASK_DAILY_LIMIT = 10


@dataclass
class Deps:
    settings: Settings
    broker: TinkoffBroker
    session_factory: async_sessionmaker[AsyncSession]
    universe: Universe
    llm: LLM
    embedder: Embedder
    ask_limiter: DailyLimiter = field(default_factory=lambda: DailyLimiter(GUEST_ASK_DAILY_LIMIT))
    alert_throttles: dict = field(default_factory=dict)  # chat_id -> AlertThrottle
