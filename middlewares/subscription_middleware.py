from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Settings
from database.queries import QueryService
from keyboards.inline import subscription_keyboard
from utils.helpers import is_subscription_related_event
from utils.texts import SUBSCRIPTION_REQUIRED_TEXT


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, queries: QueryService, settings: Settings) -> None:
        self.queries = queries
        self.settings = settings

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        if is_subscription_related_event(event):
            return await handler(event, data)

        telegram_id = None
        if isinstance(event, Message) and event.from_user:
            telegram_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            telegram_id = event.from_user.id

        if not telegram_id:
            return await handler(event, data)

        user = await self.queries.get_user_by_telegram_id(telegram_id)
        if not user or bool(user.get('is_subscribed')):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(self.settings.channel_link))
            return None
        if isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(self.settings.channel_link))
            await event.answer()
            return None
        return await handler(event, data)
