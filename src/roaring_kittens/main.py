import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from openai import AsyncOpenAI

from roaring_kittens.ai.embeddings import Embedder
from roaring_kittens.ai.llm import LLM, make_db_usage_logger
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings
from roaring_kittens.db.engine import make_engine, make_session_factory
from roaring_kittens.db.owner import claim_owner
from roaring_kittens.db.schema import ensure_schema
from roaring_kittens.deps import Deps
from roaring_kittens.logging_setup import configure_logging
from roaring_kittens.scheduler import build_scheduler, poll_news
from roaring_kittens.telegram.handlers import all_routers
from roaring_kittens.universe.universe import Universe

log = structlog.get_logger()


async def run() -> None:
    configure_logging()
    settings = Settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    await ensure_schema(engine)  # идемпотентно: создаёт таблицы при первом старте

    # Если владелец задан через env — фиксируем заранее; иначе первый /start займёт слот.
    if settings.admin_telegram_id:
        async with session_factory() as session:
            await claim_owner(session, settings.admin_telegram_id)
            await session.commit()

    # Миграция 4b: владелец из bot_state -> users(admin), старые тезисы -> его owner_id.
    # Идемпотентно; свежую инсталляцию (/start после старта) закрывает start.py.
    from sqlalchemy import text as sa_text

    from roaring_kittens.db.owner import fetch_owner_id
    from roaring_kittens.db.users import get_user, upsert_user

    owner_id = await fetch_owner_id(session_factory)
    if owner_id is not None:
        async with session_factory() as session:
            if await get_user(session, owner_id) is None:
                await upsert_user(session, owner_id, role="admin")
                log.info("owner_migrated_to_admin", owner=owner_id)
            await session.execute(sa_text(
                "UPDATE theses SET owner_id = :o WHERE owner_id IS NULL"),
                {"o": owner_id})
            await session.commit()

    broker = TinkoffBroker(settings.tinkoff_token)
    universe = Universe(broker=broker)
    await universe.load()

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    usage_logger = make_db_usage_logger(session_factory)
    llm = LLM(client=openai_client, usage_logger=usage_logger)
    embedder = Embedder(client=openai_client, usage_logger=usage_logger)
    deps = Deps(settings=settings, broker=broker, session_factory=session_factory,
                universe=universe, llm=llm, embedder=embedder)

    bot = Bot(token=settings.telegram_bot_token,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(deps=deps)
    dp.include_router(all_routers)

    scheduler = build_scheduler(deps, bot)
    scheduler.start()
    await poll_news(deps, bot)  # первый прогон сразу при старте, чтобы БД не была пустой

    log.info("bot_starting", owner_env=settings.admin_telegram_id)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
