from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

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
        self.trial_days = int(os.getenv('TRIAL_DAYS', '7'))
        self.reminder_hours_before_end = int(
            os.getenv(
                'SUBSCRIPTION_REMINDER_HOURS',
                str(getattr(settings, 'reminder_hours_before_end', 24) or 24),
            )
        )
        self.reminder_loop_interval_seconds = int(
            os.getenv(
                'SUBSCRIPTION_REMINDER_LOOP_SECONDS',
                str(getattr(settings, 'reminder_loop_interval_seconds', 3600) or 3600),
            )
        )
        self.lifetime_usernames = {
            item.strip().lstrip('@').lower()
            for item in os.getenv('LIFETIME_ACCESS_USERNAMES', '').split(',')
            if item.strip()
        }

    async def bootstrap(self) -> None:
        await self.queries.sync_subscription_plans(self.settings.subscription_plans)

    async def get_status(self, user_id: int) -> dict[str, object]:
        lifetime_reason = await self._get_lifetime_reason(user_id)
        if lifetime_reason:
            return {
                'status': 'active',
                'is_payment_enabled': self.settings.payment_enabled,
                'starts_at': None,
                'ends_at': None,
                'ends_at_human': 'Без ограничения',
                'days_left': None,
                'hours_left': None,
                'plan_title': lifetime_reason,
                'plan_code': 'lifetime',
                'reminder_sent_at': None,
                'subscription_id': None,
            }

        subscription = await self.queries.ensure_user_subscription(user_id, self.trial_days)
        now = datetime.now(timezone.utc)
        ends_at = self._parse_dt(subscription.get('ends_at'))
        status = str(subscription.get('status') or 'trial')

        if ends_at and ends_at.year >= 2099 and status == 'active':
            return {
                'status': 'active',
                'is_payment_enabled': self.settings.payment_enabled,
                'starts_at': subscription.get('starts_at'),
                'ends_at': subscription.get('ends_at'),
                'ends_at_human': 'Без ограничения',
                'days_left': None,
                'hours_left': None,
                'plan_title': 'Ручной безлимитный доступ',
                'plan_code': 'manual_lifetime',
                'reminder_sent_at': None,
                'subscription_id': subscription.get('id'),
            }

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

        plan_title = subscription.get('plan_title')
        if not plan_title and status == 'trial':
            plan_title = f'Бесплатный период · {self.trial_days} дней'

        return {
            'status': status,
            'is_payment_enabled': self.settings.payment_enabled,
            'starts_at': subscription.get('starts_at'),
            'ends_at': subscription.get('ends_at'),
            'ends_at_human': format_dt_human(subscription.get('ends_at')),
            'days_left': days_left,
            'hours_left': hours_left,
            'plan_title': plan_title or '—',
            'plan_code': subscription.get('plan_code'),
            'reminder_sent_at': subscription.get('reminder_sent_at'),
            'subscription_id': subscription.get('id'),
        }

    async def can_use_bot(self, user_id: int) -> bool:
        if await self._get_lifetime_reason(user_id):
            return True
        if not self.settings.payment_enabled:
            return True
        status = await self.get_status(user_id)
        return str(status['status']) in {'trial', 'active'}

    async def activate_plan_from_payment(self, user_id: int, plan_id: int, payment_id: int) -> dict[str, object]:
        current = await self.queries.ensure_user_subscription(user_id, self.trial_days)
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
            await asyncio.sleep(self.reminder_loop_interval_seconds)

    async def send_expiring_reminders(self, bot: Bot) -> None:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=self.reminder_hours_before_end)
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

    async def grant_access_by_username(self, username: str, days: int | None = None) -> dict[str, object] | None:
        normalized = username.strip().lstrip('@').lower()
        if not normalized:
            return None
        row = await self.queries.db.fetchone(
            'SELECT id FROM users WHERE lower(username) = lower(?)',
            (normalized,),
        )
        if not row:
            return None

        user_id = int(row['id'])
        now = datetime.now(timezone.utc)
        if days is None:
            ends_at = '2099-12-31T23:59:59+00:00'
            status = 'active'
        else:
            current = await self.queries.ensure_user_subscription(user_id, self.trial_days)
            current_end = self._parse_dt(current.get('ends_at'))
            base_dt = current_end if current_end and current_end > now and current.get('status') in {'trial', 'active'} else now
            ends_at = (base_dt + timedelta(days=days)).isoformat()
            status = 'active'

        await self.queries.update_user_subscription(
            user_id,
            status=status,
            ends_at=ends_at,
            reminder_sent_at=None,
        )
        return await self.get_status(user_id)

    async def revoke_access_by_username(self, username: str) -> bool:
        normalized = username.strip().lstrip('@').lower()
        if not normalized:
            return False
        row = await self.queries.db.fetchone(
            'SELECT id FROM users WHERE lower(username) = lower(?)',
            (normalized,),
        )
        if not row:
            return False
        await self.queries.update_user_subscription(
            int(row['id']),
            status='expired',
            ends_at=datetime.now(timezone.utc).isoformat(),
            reminder_sent_at=None,
        )
        return True

    async def _get_lifetime_reason(self, user_id: int) -> str | None:
        row = await self.queries.db.fetchone(
            'SELECT telegram_id, username, is_admin FROM users WHERE id = ?',
            (user_id,),
        )
        if not row:
            return None

        telegram_id = int(row['telegram_id']) if row['telegram_id'] is not None else None
        username = (row['username'] or '').strip().lstrip('@').lower()
        is_admin = bool(row['is_admin']) or (telegram_id in self.settings.admin_ids if telegram_id is not None else False)

        if is_admin:
            return 'Безлимитный доступ администратора'
        if username and username in self.lifetime_usernames:
            return 'Безлимитный доступ по логину'
        return None

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
