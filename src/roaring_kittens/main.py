import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from openai import AsyncOpenAI

from roaring_kittens.ai.llm import LLM, make_db_usage_logger
from roaring_kittens.broker.tinkoff_client import TinkoffBroker
from roaring_kittens.config import Settings
from roaring_kittens.db.engine import make_engine, make_session_factory
from roaring_kittens.deps import Deps
from roaring_kittens.logging_setup import configure_logging
from roaring_kittens.scheduler import build_scheduler, poll_news
from roaring_kittens.telegram.handlers import all_routers
from roaring_kittens.telegram.middleware import AllowListMiddleware
from roaring_kittens.universe.universe import Universe

log = structlog.get_logger()


async def run() -> None:
    configure_logging()
    settings = Settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    broker = TinkoffBroker(settings.tinkoff_token)
    universe = Universe(broker=broker)
    await universe.load()

    llm = LLM(client=AsyncOpenAI(api_key=settings.openai_api_key),
              usage_logger=make_db_usage_logger(session_factory))
    deps = Deps(settings=settings, broker=broker, session_factory=session_factory,
                universe=universe, llm=llm)

    bot = Bot(token=settings.telegram_bot_token,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(deps=deps)
    dp.message.middleware(AllowListMiddleware({settings.admin_telegram_id}))
    dp.include_router(all_routers)

    scheduler = build_scheduler(deps, bot)
    scheduler.start()
    await poll_news(deps)  # первый прогон сразу при старте, чтобы БД не была пустой

    log.info("bot_starting", admin=settings.admin_telegram_id)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
