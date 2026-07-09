from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database.db import Database


LIMIT_FIELDS = {
    'posts_left',
    'cta_left',
    'ideas_left',
    'improvements_left',
    'images_left',
    'voice_posts_left',
    'content_plans_left',
    'channel_reviews_left',
    'manual_post_reviews_left',
}


class QueryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_or_update_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        full_name: str | None,
        is_admin: bool,
        trial_days: int = 3,
        source: str | None = None,
        utm_source: str | None = None,
        utm_campaign: str | None = None,
    ) -> int:
        existing = await self.db.fetchone('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        if existing:
            await self.db.execute(
                '''
                UPDATE users
                SET username = ?,
                    first_name = ?,
                    full_name = ?,
                    is_admin = ?,
                    source = COALESCE(NULLIF(?, ''), source),
                    utm_source = COALESCE(NULLIF(?, ''), utm_source),
                    utm_campaign = COALESCE(NULLIF(?, ''), utm_campaign),
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
                ''',
                (username, first_name, full_name, int(is_admin), source or '', utm_source or '', utm_campaign or '', telegram_id),
            )
            row = await self.db.fetchone('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            await self.ensure_user_limits(int(row['id']))
            return int(row['id'])

        cursor = await self.db.execute(
            '''
            INSERT INTO users (
                telegram_id, username, first_name, full_name, is_admin, source, utm_source, utm_campaign
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (telegram_id, username, first_name, full_name, int(is_admin), source or 'direct', utm_source, utm_campaign),
        )
        user_id = int(cursor.lastrowid)
        await self.db.execute('INSERT OR IGNORE INTO brand_profiles (user_id) VALUES (?)', (user_id,))
        await self.ensure_user_limits(user_id)
        now = datetime.now(timezone.utc)
        trial_end = now + timedelta(days=trial_days)
        await self.db.execute(
            '''
            INSERT OR IGNORE INTO subscriptions_stub (
                user_id, trial_started_at, trial_ends_at, subscription_status, is_payment_enabled
            ) VALUES (?, ?, ?, 'trial', 0)
            ''',
            (user_id, now.isoformat(), trial_end.isoformat()),
        )
        await self.db.execute(
            'INSERT OR IGNORE INTO referrals_stub (user_id, referral_code) VALUES (?, ?)',
            (user_id, f'ref{telegram_id}'),
        )
        await self.db.execute(
            '''
            INSERT OR IGNORE INTO user_subscriptions (user_id, status, starts_at, ends_at)
            VALUES (?, 'trial', ?, ?)
            ''',
            (user_id, now.isoformat(), trial_end.isoformat()),
        )
        return user_id

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM users WHERE id = ?', (user_id,))
        return dict(row) if row else None

    async def set_user_subscription(self, telegram_id: int, value: bool) -> None:
        await self.db.execute(
            'UPDATE users SET is_subscribed = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?',
            (int(value), telegram_id),
        )

    async def set_onboarding_completed(self, telegram_id: int, value: bool) -> None:
        await self.db.execute(
            'UPDATE users SET is_onboarding_completed = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?',
            (int(value), telegram_id),
        )

    async def get_brand_profile(self, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM brand_profiles WHERE user_id = ?', (user_id,))
        return dict(row) if row else None

    async def update_brand_profile(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ', '.join([f'{key} = ?' for key in fields])
        params = list(fields.values()) + [user_id]
        await self.db.execute(
            f'UPDATE brand_profiles SET {columns}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            params,
        )

    async def add_user_example(self, user_id: int, example_text: str) -> None:
        await self.db.execute('INSERT INTO user_examples (user_id, example_text) VALUES (?, ?)', (user_id, example_text))

    async def clear_user_examples(self, user_id: int) -> None:
        await self.db.execute('DELETE FROM user_examples WHERE user_id = ?', (user_id,))

    async def get_user_examples(self, user_id: int, limit: int = 5) -> list[str]:
        rows = await self.db.fetchall(
            'SELECT example_text FROM user_examples WHERE user_id = ? ORDER BY id DESC LIMIT ?',
            (user_id, limit),
        )
        return [str(row['example_text']) for row in rows]

    async def get_memory_summary(self, user_id: int) -> str:
        row = await self.db.fetchone('SELECT summary_text FROM brand_memory_summaries WHERE user_id = ?', (user_id,))
        return str(row['summary_text']) if row and row['summary_text'] else ''

    async def upsert_memory_summary(self, user_id: int, summary_text: str) -> None:
        await self.db.execute(
            '''
            INSERT INTO brand_memory_summaries (user_id, summary_text, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET summary_text = excluded.summary_text, updated_at = CURRENT_TIMESTAMP
            ''',
            (user_id, summary_text),
        )

    async def add_generation_history(
        self,
        user_id: int,
        generation_type: str,
        source_type: str,
        input_text: str,
        output_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = await self.db.execute(
            '''
            INSERT INTO generation_history (user_id, generation_type, source_type, input_text, output_text, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (user_id, generation_type, source_type, input_text, output_text, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)

    async def get_generation_history(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            'SELECT * FROM generation_history WHERE user_id = ? ORDER BY id DESC LIMIT ?',
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_generation_record(self, record_id: int, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            'SELECT * FROM generation_history WHERE id = ? AND user_id = ?',
            (record_id, user_id),
        )
        return dict(row) if row else None

    async def delete_generation_record(self, record_id: int, user_id: int) -> None:
        await self.db.execute('DELETE FROM generation_history WHERE id = ? AND user_id = ?', (record_id, user_id))

    async def clear_generation_history(self, user_id: int) -> None:
        await self.db.execute('DELETE FROM generation_history WHERE user_id = ?', (user_id,))

    async def set_free_analysis_used(self, user_id: int, value: bool = True) -> None:
        await self.db.execute(
            'UPDATE users SET used_free_analysis = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (int(value), user_id),
        )

    async def update_user_tariff(
        self,
        user_id: int,
        tariff_code: str,
        started_at: str,
        expires_at: str | None,
        is_premium: bool = False,
    ) -> None:
        await self.db.execute(
            '''
            UPDATE users
            SET current_tariff = ?,
                tariff_started_at = ?,
                tariff_expires_at = ?,
                is_premium = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (tariff_code, started_at, expires_at, int(is_premium), user_id),
        )

    async def ensure_user_limits(self, user_id: int) -> dict[str, Any]:
        await self.db.execute('INSERT OR IGNORE INTO user_limits (user_id) VALUES (?)', (user_id,))
        row = await self.db.fetchone('SELECT * FROM user_limits WHERE user_id = ?', (user_id,))
        return dict(row) if row else {}

    async def get_user_limits(self, user_id: int) -> dict[str, Any]:
        return await self.ensure_user_limits(user_id)

    async def add_user_limits(self, user_id: int, limits: dict[str, Any], reset_at: str | None = None) -> None:
        await self.ensure_user_limits(user_id)
        clean_limits = {key: int(value or 0) for key, value in limits.items() if key in LIMIT_FIELDS and int(value or 0) > 0}
        if clean_limits:
            columns = ', '.join([f'{key} = COALESCE({key}, 0) + ?' for key in clean_limits])
            params: list[Any] = list(clean_limits.values())
            params.append(reset_at)
            params.append(user_id)
            await self.db.execute(
                f'''
                UPDATE user_limits
                SET {columns},
                    reset_at = CASE
                        WHEN ? IS NULL THEN reset_at
                        WHEN reset_at IS NULL THEN ?
                        WHEN reset_at < ? THEN ?
                        ELSE reset_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                ''',
                list(clean_limits.values()) + [reset_at, reset_at, reset_at, reset_at, user_id],
            )
            return
        if reset_at:
            await self.db.execute(
                '''
                UPDATE user_limits
                SET reset_at = CASE
                        WHEN reset_at IS NULL THEN ?
                        WHEN reset_at < ? THEN ?
                        ELSE reset_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                ''',
                (reset_at, reset_at, reset_at, user_id),
            )

    async def has_limit(self, user_id: int, field: str) -> bool:
        if field not in LIMIT_FIELDS:
            raise ValueError(f'Unknown limit field: {field}')
        row = await self.db.fetchone(f'SELECT COALESCE({field}, 0) AS value FROM user_limits WHERE user_id = ?', (user_id,))
        return bool(row and int(row['value'] or 0) > 0)

    async def consume_limit(self, user_id: int, field: str, amount: int = 1) -> bool:
        if field not in LIMIT_FIELDS:
            raise ValueError(f'Unknown limit field: {field}')
        await self.ensure_user_limits(user_id)
        cursor = await self.db.execute(
            f'''
            UPDATE user_limits
            SET {field} = {field} - ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND COALESCE({field}, 0) >= ?
            ''',
            (amount, user_id, amount),
        )
        return bool(cursor.rowcount)

    async def set_user_limit(self, user_id: int, field: str, value: int) -> None:
        if field not in LIMIT_FIELDS:
            raise ValueError(f'Unknown limit field: {field}')
        await self.ensure_user_limits(user_id)
        await self.db.execute(
            f'UPDATE user_limits SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (max(0, int(value)), user_id),
        )

    async def add_analysis(
        self,
        user_id: int,
        original_text: str,
        post_goal: str | None,
        result_text: str,
        score: int | None = None,
        is_free: bool = True,
    ) -> int:
        cursor = await self.db.execute(
            '''
            INSERT INTO analyses (user_id, original_text, post_goal, score, result_text, is_free)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (user_id, original_text, post_goal, score, result_text, int(is_free)),
        )
        return int(cursor.lastrowid)

    async def create_manual_review_request(self, user_id: int, request_type: str, content: str) -> int:
        cursor = await self.db.execute(
            '''
            INSERT INTO manual_review_requests (user_id, request_type, content)
            VALUES (?, ?, ?)
            ''',
            (user_id, request_type, content),
        )
        return int(cursor.lastrowid)

    async def get_manual_review_request(self, request_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            '''
            SELECT mrr.*, u.telegram_id, u.username, u.first_name, u.full_name
            FROM manual_review_requests mrr
            JOIN users u ON u.id = mrr.user_id
            WHERE mrr.id = ?
            ''',
            (request_id,),
        )
        return dict(row) if row else None

    async def list_manual_review_requests(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if status:
            rows = await self.db.fetchall(
                '''
                SELECT mrr.*, u.telegram_id, u.username, u.first_name, u.full_name
                FROM manual_review_requests mrr
                JOIN users u ON u.id = mrr.user_id
                WHERE mrr.status = ?
                ORDER BY mrr.id DESC LIMIT ?
                ''',
                (status, limit),
            )
        else:
            rows = await self.db.fetchall(
                '''
                SELECT mrr.*, u.telegram_id, u.username, u.first_name, u.full_name
                FROM manual_review_requests mrr
                JOIN users u ON u.id = mrr.user_id
                ORDER BY mrr.id DESC LIMIT ?
                ''',
                (limit,),
            )
        return [dict(row) for row in rows]

    async def update_manual_review_request(self, request_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {'status', 'admin_response', 'completed_at'}
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return
        columns = ', '.join([f'{key} = ?' for key in clean])
        params = list(clean.values()) + [request_id]
        await self.db.execute(f'UPDATE manual_review_requests SET {columns} WHERE id = ?', params)

    async def log_admin_event(self, level: str, action: str, details: str = '') -> None:
        await self.db.execute('INSERT INTO admin_logs (level, action, details) VALUES (?, ?, ?)', (level, action, details))

    async def get_admin_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetchall('SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,))
        return [dict(row) for row in rows]

    async def get_admin_stats(self) -> dict[str, Any]:
        users = await self.db.fetchone('SELECT COUNT(*) AS cnt FROM users')
        active = await self.db.fetchone(
            "SELECT COUNT(DISTINCT user_id) AS cnt FROM generation_history WHERE created_at >= datetime('now', '-7 days')"
        )
        generations = await self.db.fetchone('SELECT COUNT(*) AS cnt FROM generation_history')
        active_subs = await self.db.fetchone("SELECT COUNT(*) AS cnt FROM user_subscriptions WHERE status = 'active'")
        expired_subs = await self.db.fetchone("SELECT COUNT(*) AS cnt FROM user_subscriptions WHERE status = 'expired'")
        payments = await self.db.fetchone("SELECT COUNT(*) AS cnt FROM payments WHERE status = 'paid'")
        latest = await self.db.fetchall('SELECT first_name, full_name, created_at FROM users ORDER BY id DESC LIMIT 5')
        return {
            'users': int(users['cnt']) if users else 0,
            'active_users': int(active['cnt']) if active else 0,
            'generations': int(generations['cnt']) if generations else 0,
            'active_subscriptions': int(active_subs['cnt']) if active_subs else 0,
            'expired_subscriptions': int(expired_subs['cnt']) if expired_subs else 0,
            'paid_payments': int(payments['cnt']) if payments else 0,
            'latest_users': [dict(row) for row in latest],
        }

    async def get_subscription_stub(self, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM subscriptions_stub WHERE user_id = ?', (user_id,))
        return dict(row) if row else None

    async def update_subscription_stub(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ', '.join([f'{key} = ?' for key in fields])
        params = list(fields.values()) + [user_id]
        await self.db.execute(f'UPDATE subscriptions_stub SET {columns} WHERE user_id = ?', params)

    async def sync_subscription_plans(self, plans: list[dict[str, Any]]) -> None:
        await self.db.execute('UPDATE subscription_plans SET is_active = 0, updated_at = CURRENT_TIMESTAMP')
        for plan in plans:
            limits = plan.get('limits') or plan.get('limits_json') or {}
            limits_json = limits if isinstance(limits, str) else json.dumps(limits, ensure_ascii=False)
            await self.db.execute(
                '''
                INSERT INTO subscription_plans (
                    code, title, duration_days, price_rub, plan_type, description, limits_json, is_active, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    title = excluded.title,
                    duration_days = excluded.duration_days,
                    price_rub = excluded.price_rub,
                    plan_type = excluded.plan_type,
                    description = excluded.description,
                    limits_json = excluded.limits_json,
                    is_active = excluded.is_active,
                    sort_order = excluded.sort_order,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    plan['code'],
                    plan['title'],
                    int(plan['duration_days']),
                    int(plan['price_rub']),
                    plan.get('plan_type') or 'subscription_30_days',
                    plan.get('description') or '',
                    limits_json,
                    int(bool(plan.get('is_active', True))),
                    int(plan.get('sort_order', 0)),
                ),
            )

    async def get_subscription_plans(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = 'SELECT * FROM subscription_plans'
        params: list[Any] = []
        if active_only:
            query += ' WHERE is_active = 1'
        query += ' ORDER BY sort_order ASC, price_rub ASC'
        rows = await self.db.fetchall(query, params)
        return [dict(row) for row in rows]

    async def get_plan_by_code(self, code: str) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM subscription_plans WHERE code = ?', (code,))
        return dict(row) if row else None

    async def get_plan_by_id(self, plan_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM subscription_plans WHERE id = ?', (plan_id,))
        return dict(row) if row else None

    async def ensure_user_subscription(self, user_id: int, trial_days: int = 3) -> dict[str, Any]:
        row = await self.db.fetchone('SELECT * FROM user_subscriptions WHERE user_id = ?', (user_id,))
        if row:
            return dict(row)
        stub = await self.get_subscription_stub(user_id)
        now = datetime.now(timezone.utc)
        starts_at = stub.get('trial_started_at') if stub else now.isoformat()
        ends_at = stub.get('trial_ends_at') if stub else (now + timedelta(days=trial_days)).isoformat()
        await self.db.execute(
            '''
            INSERT INTO user_subscriptions (user_id, status, starts_at, ends_at)
            VALUES (?, 'trial', ?, ?)
            ''',
            (user_id, starts_at, ends_at),
        )
        created = await self.db.fetchone('SELECT * FROM user_subscriptions WHERE user_id = ?', (user_id,))
        return dict(created)

    async def get_user_subscription(self, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            '''
            SELECT us.*, sp.code AS plan_code, sp.title AS plan_title, sp.duration_days AS plan_duration_days, sp.price_rub AS plan_price_rub
            FROM user_subscriptions us
            LEFT JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.user_id = ?
            ''',
            (user_id,),
        )
        return dict(row) if row else None

    async def update_user_subscription(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ', '.join([f'{key} = ?' for key in fields])
        params = list(fields.values()) + [user_id]
        await self.db.execute(
            f'UPDATE user_subscriptions SET {columns}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            params,
        )

    async def create_payment(
        self,
        user_id: int,
        plan_id: int,
        amount: float,
        description: str,
        shp_payload: dict[str, Any],
        provider: str = 'robokassa',
        payment_mode: str = 'generated_invoice',
    ) -> int:
        cursor = await self.db.execute(
            '''
            INSERT INTO payments (
                user_id, plan_id, provider, payment_mode, amount, status, description, shp_payload_json, provider_payload_json
            ) VALUES (?, ?, ?, ?, ?, 'created', ?, ?, ?)
            ''',
            (
                user_id,
                plan_id,
                provider,
                payment_mode,
                amount,
                description,
                json.dumps(shp_payload, ensure_ascii=False),
                json.dumps({}, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)

    async def update_payment(self, payment_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ', '.join([f'{key} = ?' for key in fields])
        params = list(fields.values()) + [payment_id]
        await self.db.execute(f'UPDATE payments SET {columns}, updated_at = CURRENT_TIMESTAMP WHERE id = ?', params)

    async def get_payment(self, payment_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            '''
            SELECT p.*, sp.code AS plan_code, sp.title AS plan_title, sp.duration_days AS plan_duration_days, sp.price_rub AS plan_price_rub
            FROM payments p
            LEFT JOIN subscription_plans sp ON sp.id = p.plan_id
            WHERE p.id = ?
            ''',
            (payment_id,),
        )
        return dict(row) if row else None

    async def get_payment_by_invoice_id(self, invoice_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            '''
            SELECT p.*, sp.code AS plan_code, sp.title AS plan_title, sp.duration_days AS plan_duration_days, sp.price_rub AS plan_price_rub
            FROM payments p
            LEFT JOIN subscription_plans sp ON sp.id = p.plan_id
            WHERE p.invoice_id = ?
            ORDER BY p.id DESC LIMIT 1
            ''',
            (invoice_id,),
        )
        return dict(row) if row else None

    async def get_latest_pending_payment(self, user_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone(
            '''
            SELECT p.*, sp.code AS plan_code, sp.title AS plan_title, sp.duration_days AS plan_duration_days, sp.price_rub AS plan_price_rub
            FROM payments p
            LEFT JOIN subscription_plans sp ON sp.id = p.plan_id
            WHERE p.user_id = ? AND p.status IN ('created', 'pending')
            ORDER BY p.id DESC LIMIT 1
            ''',
            (user_id,),
        )
        return dict(row) if row else None

    async def list_user_payments(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            '''
            SELECT p.*, sp.code AS plan_code, sp.title AS plan_title
            FROM payments p
            LEFT JOIN subscription_plans sp ON sp.id = p.plan_id
            WHERE p.user_id = ?
            ORDER BY p.id DESC LIMIT ?
            ''',
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def log_payment_event(self, payment_id: int | None, event_type: str, payload: dict[str, Any]) -> None:
        await self.db.execute(
            'INSERT INTO payment_events (payment_id, event_type, payload_json) VALUES (?, ?, ?)',
            (payment_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )

    async def list_expiring_subscriptions(self, cutoff_iso: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            '''
            SELECT us.*, u.telegram_id, u.first_name, u.full_name, sp.title AS plan_title
            FROM user_subscriptions us
            JOIN users u ON u.id = us.user_id
            LEFT JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.status IN ('active')
              AND us.ends_at IS NOT NULL
              AND us.ends_at <= ?
            ''',
            (cutoff_iso,),
        )
        return [dict(row) for row in rows]

    async def was_notification_sent(self, subscription_id: int, notification_type: str) -> bool:
        row = await self.db.fetchone(
            'SELECT id FROM subscription_notifications WHERE subscription_id = ? AND notification_type = ?',
            (subscription_id, notification_type),
        )
        return row is not None

    async def mark_notification_sent(self, user_id: int, subscription_id: int, notification_type: str) -> None:
        await self.db.execute(
            '''
            INSERT OR IGNORE INTO subscription_notifications (user_id, subscription_id, notification_type)
            VALUES (?, ?, ?)
            ''',
            (user_id, subscription_id, notification_type),
        )
        await self.db.execute(
            'UPDATE user_subscriptions SET reminder_sent_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (subscription_id,),
        )
