from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot

from config import Settings
from database.product_repository import ProductRepository
from services.channel_service import ChannelService
from utils.helpers import render_model_text

logger = logging.getLogger(__name__)


class PublishingService:
    def __init__(
        self,
        repository: ProductRepository,
        channel_service: ChannelService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.channel_service = channel_service
        self.settings = settings

    async def publish_draft(self, bot: Bot, draft: dict[str, Any], channel: dict[str, Any]) -> list[int]:
        can_post, _ = await self.channel_service.refresh_permissions(bot, channel)
        if not can_post:
            raise RuntimeError('Бот больше не может публиковать в канал. Проверьте его права администратора.')
        chat_id = int(channel['telegram_chat_id'])
        raw_text = str(draft.get('content_text') or '').strip()
        text = render_model_text(raw_text)
        if not text:
            raise RuntimeError('Черновик пуст.')

        message_ids: list[int] = []
        image_file_id = draft.get('image_file_id')
        if image_file_id and len(text) <= 1024:
            message = await bot.send_photo(chat_id, photo=str(image_file_id), caption=text)
            message_ids.append(message.message_id)
        else:
            for chunk in self._split_text(text):
                message = await bot.send_message(chat_id, chunk)
                message_ids.append(message.message_id)
            if image_file_id:
                message = await bot.send_photo(chat_id, photo=str(image_file_id))
                message_ids.append(message.message_id)

        published_at = datetime.now(timezone.utc).isoformat()
        for message_id in message_ids:
            await self.repository.save_channel_post(
                channel_id=int(channel['id']),
                telegram_message_id=message_id,
                content_text=text if message_id == message_ids[0] else '',
                published_at=published_at,
                source='kontursmm',
            )
        return message_ids

    async def publish_now(self, bot: Bot, user_id: int, draft_id: int) -> list[int]:
        draft = await self.repository.claim_draft_for_publication(draft_id, user_id)
        channel = await self.repository.get_active_channel(user_id)
        if not draft:
            raise ValueError('Черновик не найден, уже запланирован или опубликован.')
        if not channel:
            await self.repository.release_draft_publication(draft_id, user_id)
            raise ValueError('Сначала подключите канал.')
        if draft.get('channel_id') is not None and int(draft['channel_id']) != int(channel['id']):
            await self.repository.release_draft_publication(draft_id, user_id)
            raise ValueError('Этот черновик относится к другому каналу.')
        try:
            message_ids = await self.publish_draft(bot, draft, channel)
        except Exception:
            await self.repository.release_draft_publication(draft_id, user_id)
            raise
        await self.repository.complete_publication(draft_id, int(channel['id']), message_ids)
        return message_ids

    async def run_scheduler(self, bot: Bot) -> None:
        while True:
            try:
                while True:
                    schedule = await self.repository.claim_due_schedule(datetime.now(timezone.utc).isoformat())
                    if not schedule:
                        break
                    try:
                        message_ids = await self.publish_draft(bot, schedule, schedule)
                        await self.repository.complete_publication(
                            draft_id=int(schedule['draft_id']),
                            channel_id=int(schedule['channel_id']),
                            message_ids=message_ids,
                            schedule_id=int(schedule['id']),
                        )
                    except Exception as exc:
                        logger.exception('Scheduled publication failed: schedule_id=%s', schedule.get('id'))
                        await self.repository.fail_schedule(
                            int(schedule['id']),
                            str(exc),
                            retry_seconds=self.settings.scheduler_retry_seconds,
                            max_retries=self.settings.scheduler_max_retries,
                        )
                        try:
                            await bot.send_message(
                                int(schedule['telegram_id']),
                                '<b>Не удалось опубликовать запланированный пост.</b>\n\n'
                                'Проверьте права бота в канале. Я повторю попытку автоматически, если ещё остались повторы.',
                            )
                        except Exception:
                            logger.exception('Failed to notify user about schedule error')
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Scheduler iteration failed')
            await asyncio.sleep(self.settings.scheduler_interval_seconds)

    @staticmethod
    def _split_text(text: str, limit: int = 4096) -> list[str]:
        chunks: list[str] = []
        remaining = text
        while len(remaining) > limit:
            split_at = remaining.rfind('\n', 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind(' ', 0, limit)
            if split_at < limit // 2:
                split_at = limit
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
        return chunks
