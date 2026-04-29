from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot

from config import Settings
from database.queries import QueryService
from keyboards.inline import payment_plans_keyboard
from utils.helpers import format_dt_human, normalize_username
from utils.texts import SUBSCRIPTION_EXPIRED_TEXT, SUBSCRIPTION_REMINDER_TEXT

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self, queries: QueryService, settings: Settings) -> None:
        self.queries = queries
        self.settings = settings

    async def bootstrap(self) -> None:
        await self.queries.sync_subscription_plans(self.settings.subscription_plans)

    async def get_status(self, user_id: int) -> dict[str, object]:
        user = await self._get_user_by_id(user_id)
        if self._has_admin_or_env_lifetime_access(user):
            return self._lifetime_status(user, status='admin' if user and user.get('is_admin') else 'lifetime')

        subscription = await self.queries.ensure_user_subscription(user_id, self.settings.trial_days)
        subscription = await self._extend_old_trial_if_needed(user_id, subscription)

        now = datetime.now(timezone.utc)
        ends_at = self._parse_dt(subscription.get('ends_at'))
        status = str(subscription.get('status') or 'trial')

        if status in {'lifetime', 'admin'}:
            return self._lifetime_status(user, status=status)

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
            'plan_title': subscription.get('plan_title') or ('Бесплатный период' if status == 'trial' else '—'),
            'plan_code': subscription.get('plan_code'),
            'reminder_sent_at': subscription.get('reminder_sent_at'),
            'subscription_id': subscription.get('id'),
        }

    async def can_use_bot(self, user_id: int) -> bool:
        if not self.settings.payment_enabled:
            return True
        status = await self.get_status(user_id)
        return str(status['status']) in {'trial', 'active', 'lifetime', 'admin'}

    async def activate_plan_from_payment(self, user_id: int, plan_id: int, payment_id: int) -> dict[str, object]:
        current = await self.queries.ensure_user_subscription(user_id, self.settings.trial_days)
        plan = await self.queries.get_plan_by_id(plan_id)
        if not plan:
            raise RuntimeError('Тариф не найден.')

        now = datetime.now(timezone.utc)
        current_end = self._parse_dt(current.get('ends_at'))
        current_status = str(current.get('status') or '')
        base_dt = current_end if current_end and current_end > now and current_status in {'trial', 'active'} else now
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

    async def grant_access_by_username(self, username: str, days: int | None = None) -> dict[str, object] | None:
        user = await self._get_user_by_username(username)
        if not user:
            return None

        user_id = int(user['id'])
        await self.queries.ensure_user_subscription(user_id, self.settings.trial_days)
        now = datetime.now(timezone.utc)

        if days is None:
            await self.queries.update_user_subscription(
                user_id,
                plan_id=None,
                status='lifetime',
                starts_at=now.isoformat(),
                ends_at=None,
                reminder_sent_at=None,
            )
        else:
            await self.queries.update_user_subscription(
                user_id,
                plan_id=None,
                status='active',
                starts_at=now.isoformat(),
                ends_at=(now + timedelta(days=days)).isoformat(),
                reminder_sent_at=None,
            )
        await self.queries.log_admin_event('INFO', 'grant_access', f'username={normalize_username(username)} days={days}')
        return await self.get_status(user_id)

    async def revoke_access_by_username(self, username: str) -> bool:
        user = await self._get_user_by_username(username)
        if not user:
            return False
        now = datetime.now(timezone.utc)
        await self.queries.ensure_user_subscription(int(user['id']), self.settings.trial_days)
        await self.queries.update_user_subscription(
            int(user['id']),
            status='expired',
            ends_at=now.isoformat(),
            reminder_sent_at=None,
        )
        await self.queries.log_admin_event('INFO', 'revoke_access', f'username={normalize_username(username)}')
        return True

    async def run_reminder_loop(self, bot: Bot) -> None:
        # First run shortly after startup, then by interval.
        while True:
            try:
                await self.send_expiring_reminders(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Subscription reminder loop failed')
            await asyncio.sleep(self.settings.reminder_loop_interval_seconds)

    async def send_expiring_reminders(self, bot: Bot) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=self.settings.reminder_hours_before_end)
        subscriptions = await self._list_expiring_subscriptions(now.isoformat(), cutoff.isoformat())
        plans = await self.queries.get_subscription_plans()

        for item in subscriptions:
            subscription_id = int(item['id'])
            if await self.queries.was_notification_sent(subscription_id, 'expires_in_24h'):
                continue
            try:
                await bot.send_message(
                    chat_id=int(item['telegram_id']),
                    text=SUBSCRIPTION_REMINDER_TEXT.format(ends_at=format_dt_human(item.get('ends_at'))),
                    reply_markup=payment_plans_keyboard(plans),
                )
                await self.queries.mark_notification_sent(int(item['user_id']), subscription_id, 'expires_in_24h')
            except Exception:
                logger.exception('Failed to send subscription reminder to telegram_id=%s', item.get('telegram_id'))

    async def build_expired_message(self, user_id: int) -> tuple[str, object]:
        status = await self.get_status(user_id)
        plans = await self.queries.get_subscription_plans()
        text = SUBSCRIPTION_EXPIRED_TEXT.format(ends_at=status.get('ends_at_human') or '—')
        return text, payment_plans_keyboard(plans)

    async def _extend_old_trial_if_needed(self, user_id: int, subscription: dict[str, Any]) -> dict[str, Any]:
        """If the old 3-day trial exists, extend it to current TRIAL_DAYS when possible."""
        if str(subscription.get('status') or '') not in {'trial', 'expired'}:
            return subscription

        starts_at = self._parse_dt(subscription.get('starts_at'))
        ends_at = self._parse_dt(subscription.get('ends_at'))
        if not starts_at or not ends_at:
            return subscription

        target_end = starts_at + timedelta(days=self.settings.trial_days)
        now = datetime.now(timezone.utc)
        old_duration = (ends_at - starts_at).total_seconds()
        target_duration = timedelta(days=self.settings.trial_days).total_seconds()

        if old_duration < target_duration and target_end > now:
            await self.queries.update_user_subscription(
                user_id,
                status='trial',
                ends_at=target_end.isoformat(),
                reminder_sent_at=None,
            )
            return await self.queries.get_user_subscription(user_id) or subscription
        return subscription

    async def _get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        row = await self.queries.db.fetchone('SELECT * FROM users WHERE id = ?', (user_id,))
        return dict(row) if row else None

    async def _get_user_by_username(self, username: str) -> dict[str, Any] | None:
        normalized = normalize_username(username)
        if not normalized:
            return None
        if normalized.isdigit():
            row = await self.queries.db.fetchone(
                'SELECT * FROM users WHERE telegram_id = ? OR id = ?',
                (int(normalized), int(normalized)),
            )
        else:
            row = await self.queries.db.fetchone(
                'SELECT * FROM users WHERE lower(username) = lower(?)',
                (normalized,),
            )
        return dict(row) if row else None

    async def _list_expiring_subscriptions(self, now_iso: str, cutoff_iso: str) -> list[dict[str, Any]]:
        rows = await self.queries.db.fetchall(
            '''
            SELECT us.*, u.telegram_id, u.first_name, u.full_name, u.username, u.is_admin, sp.title AS plan_title
            FROM user_subscriptions us
            JOIN users u ON u.id = us.user_id
            LEFT JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.status IN ('trial', 'active')
              AND COALESCE(u.is_admin, 0) = 0
              AND us.ends_at IS NOT NULL
              AND us.ends_at > ?
              AND us.ends_at <= ?
            ''',
            (now_iso, cutoff_iso),
        )
        return [dict(row) for row in rows]

    def _has_admin_or_env_lifetime_access(self, user: dict[str, Any] | None) -> bool:
        if not user:
            return False
        if bool(user.get('is_admin')):
            return True
        username = normalize_username(user.get('username'))
        return bool(username and username in self.settings.lifetime_access_usernames)

    @staticmethod
    def _lifetime_status(user: dict[str, Any] | None, status: str = 'lifetime') -> dict[str, object]:
        return {
            'status': status,
            'is_payment_enabled': True,
            'starts_at': None,
            'ends_at': None,
            'ends_at_human': 'Без ограничения',
            'days_left': None,
            'hours_left': None,
            'plan_title': 'Админ-доступ' if status == 'admin' else 'Безлимитный доступ',
            'plan_code': status,
            'reminder_sent_at': None,
            'subscription_id': None,
        }

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
