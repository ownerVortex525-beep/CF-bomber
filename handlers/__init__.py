from aiogram import Router

from handlers import start
from handlers import menu
from handlers import bomb
from handlers import referral_redeem
from handlers import admin


def register_all(dp) -> None:
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(bomb.router)
    dp.include_router(referral_redeem.router)
    dp.include_router(admin.router)