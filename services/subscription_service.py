from __future__ import annotations

from datetime import datetime, timezone

from config import Settings
from database.queries import QueryService


class SubscriptionService:
    def __init__(self, queries: QueryService, settings: Settings) -> None:
        self.queries = queries
        self.settings = settings

    async def get_status(self, user_id: int) -> dict[str, str | bool]:
        row = await self.queries.get_subscription_stub(user_id)
        if not row:
            return {'subscription_status': 'trial', 'is_payment_enabled': self.settings.payment_enabled, 'trial_active': True}
        trial_ends_at = row.get('trial_ends_at')
        trial_active = True
        if trial_ends_at:
            try:
                trial_active = datetime.fromisoformat(trial_ends_at) > datetime.now(timezone.utc)
            except ValueError:
                trial_active = True
        return {
            'subscription_status': row.get('subscription_status', 'trial'),
            'is_payment_enabled': bool(row.get('is_payment_enabled', 0)),
            'trial_active': trial_active,
        }

    async def can_use_bot(self, user_id: int) -> bool:
        status = await self.get_status(user_id)
        if not self.settings.payment_enabled:
            return True
        return bool(status['trial_active']) or status['subscription_status'] == 'active'
