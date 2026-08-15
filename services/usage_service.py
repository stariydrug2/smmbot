from __future__ import annotations

from dataclasses import dataclass

from database.product_repository import ProductRepository
from database.queries import QueryService


FEATURE_LIMITS = {
    'post': 'posts_left',
    'rewrite': 'improvements_left',
    'improve': 'improvements_left',
    'cta': 'cta_left',
    'ideas': 'ideas_left',
    'topic_intercept': 'ideas_left',
    'content_plan': 'content_plans_left',
    'voice_post': 'voice_posts_left',
    'image': 'images_left',
    'channel_analysis': 'improvements_left',
}


@dataclass(slots=True)
class Reservation:
    id: int
    source: str
    feature: str
    limit_field: str | None


class UsageService:
    def __init__(self, queries: QueryService, repository: ProductRepository) -> None:
        self.queries = queries
        self.repository = repository

    async def reserve(self, user_id: int, feature: str) -> Reservation | None:
        user = await self.queries.get_user_by_id(user_id)
        if not user:
            return None
        subscription = await self.queries.get_user_subscription(user_id)
        subscription_status = str((subscription or {}).get('status') or '')
        manually_unlimited = subscription_status in {'lifetime', 'manual'} or (
            subscription_status == 'active' and not (subscription or {}).get('plan_id')
        )
        limit_field = FEATURE_LIMITS.get(feature)
        reserved = await self.repository.reserve_usage(
            user_id=user_id,
            feature=feature,
            limit_field=limit_field,
            is_admin=bool(user.get('is_admin')),
            unlimited_source='manual' if manually_unlimited else None,
        )
        if not reserved:
            return None
        return Reservation(**reserved)

    async def commit(self, reservation: Reservation) -> None:
        await self.repository.commit_usage(reservation.id)

    async def refund(self, reservation: Reservation) -> None:
        await self.repository.refund_usage(reservation.id)

    async def status(self, user_id: int) -> dict[str, object]:
        user = await self.queries.get_user_by_id(user_id)
        trial = await self.repository.refresh_trial_status(user_id, self._now())
        limits = await self.queries.get_user_limits(user_id)
        return {
            'is_admin': bool(user and user.get('is_admin')),
            'trial': trial,
            'limits': limits,
        }

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


class AccessRequiredError(RuntimeError):
    pass
