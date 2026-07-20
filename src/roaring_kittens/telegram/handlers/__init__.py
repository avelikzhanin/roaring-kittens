from aiogram import Router

from roaring_kittens.telegram.handlers import (
    ask, council, digest, portfolio, seed, start, thesis, track, watchlist,
)

all_routers = Router()
all_routers.include_router(start.router)
all_routers.include_router(portfolio.router)
all_routers.include_router(ask.router)
all_routers.include_router(digest.router)
all_routers.include_router(track.router)
all_routers.include_router(seed.router)
all_routers.include_router(council.router)
all_routers.include_router(thesis.router)
all_routers.include_router(watchlist.router)
