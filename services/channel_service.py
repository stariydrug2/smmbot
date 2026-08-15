from __future__ import annotations

from typing import Any

from aiogram import Bot

from config import Settings
from database.product_repository import ProductRepository


class ChannelService:
    def __init__(self, repository: ProductRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def connect(self, bot: Bot, user_id: int, telegram_user_id: int, chat_id: int) -> dict[str, Any]:
        chat = await bot.get_chat(chat_id)
        if str(getattr(chat, 'type', '')) not in {'channel', 'ChatType.CHANNEL'}:
            raise ValueError('Нужно выбрать именно Telegram-канал.')

        me = await bot.get_me()
        bot_member = await bot.get_chat_member(chat_id, me.id)
        user_member = await bot.get_chat_member(chat_id, telegram_user_id)
        if not self._is_admin(user_member):
            raise ValueError('Подключить канал может только его владелец или администратор.')

        can_post = self._can_post(bot_member)
        can_edit = self._can_edit(bot_member)
        if not can_post:
            raise ValueError(
                'Боту не хватает права публикации. Добавьте его администратором канала '
                'с правом «Публиковать сообщения», затем подключите канал ещё раз.'
            )

        return await self.repository.connect_channel(
            user_id=user_id,
            telegram_chat_id=chat_id,
            title=str(getattr(chat, 'title', None) or 'Telegram-канал'),
            username=getattr(chat, 'username', None),
            timezone_name=self.settings.default_channel_timezone,
            bot_can_post=can_post,
            bot_can_edit=can_edit,
        )

    async def refresh_permissions(self, bot: Bot, channel: dict[str, Any]) -> tuple[bool, bool]:
        me = await bot.get_me()
        member = await bot.get_chat_member(int(channel['telegram_chat_id']), me.id)
        can_post = self._can_post(member)
        can_edit = self._can_edit(member)
        await self.repository.update_channel_permissions(int(channel['id']), can_post, can_edit)
        return can_post, can_edit

    @staticmethod
    def _status(member: object) -> str:
        status = getattr(member, 'status', '')
        return str(getattr(status, 'value', status)).lower()

    @classmethod
    def _is_admin(cls, member: object) -> bool:
        return cls._status(member) in {'administrator', 'creator'}

    @classmethod
    def _can_post(cls, member: object) -> bool:
        return cls._status(member) == 'creator' or (
            cls._status(member) == 'administrator' and bool(getattr(member, 'can_post_messages', False))
        )

    @classmethod
    def _can_edit(cls, member: object) -> bool:
        return cls._status(member) == 'creator' or (
            cls._status(member) == 'administrator' and bool(getattr(member, 'can_edit_messages', False))
        )
