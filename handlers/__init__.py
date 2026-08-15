from aiogram import Dispatcher

from .admin import router as admin_router
from .analysis import router as analysis_router
from .channel import router as channel_router
from .content import router as content_router
from .dashboard import router as dashboard_router
from .fallback import router as fallback_router
from .payments import router as payments_router
from .planning import router as planning_router
from .start import router as start_router
from .trial import router as trial_router


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(admin_router)
    # Navigation is registered before stateful flows so a persistent menu button
    # always changes section instead of becoming generation input.
    dp.include_router(dashboard_router)
    dp.include_router(channel_router)
    dp.include_router(trial_router)
    dp.include_router(payments_router)
    dp.include_router(content_router)
    dp.include_router(planning_router)
    dp.include_router(analysis_router)
    dp.include_router(fallback_router)
