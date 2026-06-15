from aiogram import Router

from roaring_kittens.telegram.handlers import portfolio, start

all_routers = Router()
all_routers.include_router(start.router)
all_routers.include_router(portfolio.router)
