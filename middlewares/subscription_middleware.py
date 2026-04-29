from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Settings
from database.queries import QueryService
from keyboards.inline import subscription_keyboard
from services.subscription_service import SubscriptionService
from utils.helpers import is_billing_exempt_event, is_subscription_related_event
from utils.texts import SUBSCRIPTION_REQUIRED_TEXT


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, queries: QueryService, settings: Settings, subscription_service: SubscriptionService) -> None:
        self.queries = queries
        self.settings = settings
        self.subscription_service = subscription_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if is_subscription_related_event(event):
            return await handler(event, data)

        telegram_id = self._extract_telegram_id(event)
        if not telegram_id:
            return await handler(event, data)

        user = await self.queries.get_user_by_telegram_id(telegram_id)
        if not user:
            return await handler(event, data)

        if not bool(user.get('is_subscribed')):
            await self._send_channel_required(event)
            return None

        if not self.settings.payment_enabled or is_billing_exempt_event(event):
            return await handler(event, data)

        can_use = await self.subscription_service.can_use_bot(int(user['id']))
        if can_use:
            return await handler(event, data)

        text, keyboard = await self.subscription_service.build_expired_message(int(user['id']))
        await self._send_billing_required(event, text, keyboard)
        return None

    @staticmethod
    def _extract_telegram_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    async def _send_channel_required(self, event: TelegramObject) -> None:
        if isinstance(event, Message):
            await event.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(self.settings.channel_link))
            return
        if isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(self.settings.channel_link))
            await event.answer()

    @staticmethod
    async def _send_billing_required(event: TelegramObject, text: str, keyboard: object) -> None:
        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard)
            return
        if isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(text, reply_markup=keyboard)
            await event.answer('Нужна активная подписка', show_alert=True)
