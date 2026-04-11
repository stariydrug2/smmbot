from aiogram import Dispatcher

from .admin import router as admin_router
from .fallback import router as fallback_router
from .generation import router as generation_router
from .history import router as history_router
from .menu import router as menu_router
from .onboarding import router as onboarding_router
from .profile import router as profile_router
from .start import router as start_router
from .subscription import router as subscription_router


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(subscription_router)
    dp.include_router(onboarding_router)
    dp.include_router(menu_router)
    dp.include_router(generation_router)
    dp.include_router(profile_router)
    dp.include_router(history_router)
    dp.include_router(admin_router)
    dp.include_router(fallback_router)
