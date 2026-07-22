from aiogram import Router

from roaring_kittens.telegram.handlers import (
    admin, ask, budget_cmd, council, digest, onboarding, portfolio, seed, start,
    thesis, track, watchlist,
)

all_routers = Router()
# onboarding ПЕРВЫМ: FSM-state waiting_token должен видеть сообщения раньше catch-all
all_routers.include_router(onboarding.router)
all_routers.include_router(start.router)
all_routers.include_router(portfolio.router)
all_routers.include_router(ask.router)
all_routers.include_router(digest.router)
all_routers.include_router(track.router)
all_routers.include_router(seed.router)
all_routers.include_router(council.router)
all_routers.include_router(thesis.router)
all_routers.include_router(watchlist.router)
all_routers.include_router(admin.router)
all_routers.include_router(budget_cmd.router)
