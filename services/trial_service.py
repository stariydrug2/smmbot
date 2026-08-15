from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import Bot

from config import Settings
from database.product_repository import ProductRepository


class TrialService:
    def __init__(self, repository: ProductRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def verify_membership(self, bot: Bot, user_id: int, telegram_user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(self.settings.channel_id, telegram_user_id)
        except Exception:
            await self.repository.clear_trial_membership_verification(user_id)
            return False
        status = getattr(member, 'status', '')
        normalized = str(getattr(status, 'value', status)).lower()
        is_member = normalized in {'member', 'administrator', 'creator'} or (
            normalized == 'restricted' and bool(getattr(member, 'is_member', False))
        )
        if is_member:
            await self.repository.mark_trial_membership_verified(user_id)
        else:
            await self.repository.clear_trial_membership_verification(user_id)
        return is_member

    async def readiness(self, user_id: int) -> dict[str, Any]:
        trial = await self.repository.refresh_trial_status(user_id, datetime.now(timezone.utc).isoformat())
        channel = await self.repository.get_active_channel(user_id)
        profile = await self.repository.get_channel_profile(int(channel['id'])) if channel else None
        return {
            'trial': trial,
            'channel': channel,
            'profile': profile,
            'membership_verified': bool(trial.get('membership_verified_at')),
            'channel_connected': bool(channel),
            'profile_complete': bool(profile and profile.get('is_complete')),
        }

    async def activate(self, user_id: int) -> dict[str, Any]:
        ready = await self.readiness(user_id)
        trial = ready['trial']
        if trial.get('status') != 'none':
            raise ValueError('Пробный период уже был активирован для этого аккаунта.')
        if not ready['membership_verified']:
            raise ValueError('Сначала подтвердите подписку на канал KonturSMM.')
        if not ready['channel_connected']:
            raise ValueError('Сначала подключите свой Telegram-канал.')
        if not ready['profile_complete']:
            raise ValueError('Сначала завершите короткую настройку канала.')
        activated = await self.repository.activate_trial(
            user_id,
            duration_hours=self.settings.trial_duration_hours,
            generation_limit=self.settings.trial_generation_limit,
        )
        if not activated:
            raise ValueError('Пробный период уже был использован.')
        return activated
