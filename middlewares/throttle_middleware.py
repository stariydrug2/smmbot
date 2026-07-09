from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, delay_seconds: float = 0.7) -> None:
        self.delay_seconds = delay_seconds
        self._last_hit: dict[int, float] = defaultdict(float)

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        if not user_id:
            return await handler(event, data)
        now = time.monotonic()
        if now - self._last_hit[user_id] < self.delay_seconds:
            if isinstance(event, CallbackQuery):
                await event.answer('Слишком быстро. Попробуйте ещё раз через секунду.')
            return None
        self._last_hit[user_id] = now
        return await handler(event, data)
