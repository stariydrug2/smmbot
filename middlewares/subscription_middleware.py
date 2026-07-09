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
    """Keeps old subscription helpers reachable without blocking the new funnel.

    The product now works by per-feature limits: free analysis first, then paid
    actions consume concrete counters. Channel subscription remains a soft step,
    so this middleware no longer blocks normal bot actions.
    """

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
        return await handler(event, data)

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
