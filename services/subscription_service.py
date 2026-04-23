from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from config import Settings
from database.queries import QueryService
from keyboards.inline import payment_plans_keyboard
from utils.helpers import format_dt_human
from utils.texts import SUBSCRIPTION_EXPIRED_TEXT, SUBSCRIPTION_REMINDER_TEXT

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self, queries: QueryService, settings: Settings) -> None:
        self.queries = queries
        self.settings = settings

    async def bootstrap(self) -> None:
        await self.queries.sync_subscription_plans(self.settings.subscription_plans)

    async def get_status(self, user_id: int) -> dict[str, object]:
        subscription = await self.queries.ensure_user_subscription(user_id, self.settings.trial_days)
        now = datetime.now(timezone.utc)
        ends_at_raw = subscription.get('ends_at')
        ends_at = self._parse_dt(ends_at_raw)
        status = str(subscription.get('status') or 'trial')
        if ends_at and ends_at <= now and status in {'trial', 'active'}:
            status = 'expired'
            await self.queries.update_user_subscription(user_id, status='expired')
            subscription = await self.queries.get_user_subscription(user_id) or subscription
            ends_at = self._parse_dt(subscription.get('ends_at'))

        days_left = None
        hours_left = None
        if ends_at:
            delta = ends_at - now
            days_left = max(0, delta.days)
            hours_left = max(0, int(delta.total_seconds() // 3600))

        return {
            'status': status,
            'is_payment_enabled': self.settings.payment_enabled,
            'starts_at': subscription.get('starts_at'),
            'ends_at': subscription.get('ends_at'),
            'ends_at_human': format_dt_human(subscription.get('ends_at')),
            'days_left': days_left,
            'hours_left': hours_left,
            'plan_title': subscription.get('plan_title') or ('Триал' if status == 'trial' else '—'),
            'plan_code': subscription.get('plan_code'),
            'reminder_sent_at': subscription.get('reminder_sent_at'),
            'subscription_id': subscription.get('id'),
        }

    async def can_use_bot(self, user_id: int) -> bool:
        if not self.settings.payment_enabled:
            return True
        status = await self.get_status(user_id)
        return str(status['status']) in {'trial', 'active'}

    async def activate_plan_from_payment(self, user_id: int, plan_id: int, payment_id: int) -> dict[str, object]:
        current = await self.queries.ensure_user_subscription(user_id, self.settings.trial_days)
        plan = await self.queries.get_plan_by_id(plan_id)
        if not plan:
            raise RuntimeError('Тариф не найден.')
        now = datetime.now(timezone.utc)
        current_end = self._parse_dt(current.get('ends_at'))
        base_dt = current_end if current_end and current_end > now and current.get('status') in {'trial', 'active'} else now
        starts_at = current.get('starts_at') or now.isoformat()
        ends_at = base_dt + timedelta(days=int(plan['duration_days']))
        await self.queries.update_user_subscription(
            user_id,
            plan_id=plan_id,
            status='active',
            starts_at=starts_at,
            ends_at=ends_at.isoformat(),
            last_payment_id=payment_id,
            reminder_sent_at=None,
        )
        return await self.get_status(user_id)

    async def run_reminder_loop(self, bot: Bot) -> None:
        while True:
            try:
                await self.send_expiring_reminders(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Subscription reminder loop failed')
            await asyncio.sleep(self.settings.reminder_loop_interval_seconds)

    async def send_expiring_reminders(self, bot: Bot) -> None:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=self.settings.reminder_hours_before_end)
        subscriptions = await self.queries.list_expiring_subscriptions(cutoff.isoformat())
        for item in subscriptions:
            subscription_id = int(item['id'])
            if await self.queries.was_notification_sent(subscription_id, 'expires_in_24h'):
                continue
            try:
                await bot.send_message(
                    chat_id=int(item['telegram_id']),
                    text=SUBSCRIPTION_REMINDER_TEXT.format(ends_at=format_dt_human(item.get('ends_at'))),
                    reply_markup=payment_plans_keyboard(await self.queries.get_subscription_plans()),
                )
                await self.queries.mark_notification_sent(int(item['user_id']), subscription_id, 'expires_in_24h')
            except Exception:
                logger.exception('Failed to send subscription reminder to telegram_id=%s', item.get('telegram_id'))

    async def build_expired_message(self, user_id: int) -> tuple[str, object]:
        status = await self.get_status(user_id)
        plans = await self.queries.get_subscription_plans()
        text = SUBSCRIPTION_EXPIRED_TEXT.format(ends_at=status.get('ends_at_human') or '—')
        return text, payment_plans_keyboard(plans)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
