from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database.db import Database


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
    ) -> int:
        existing = await self.db.fetchone('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        if existing:
            await self.db.execute(
                '''
                UPDATE users
                SET username = ?, first_name = ?, full_name = ?, is_admin = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
                ''',
                (username, first_name, full_name, int(is_admin), telegram_id),
            )
            row = await self.db.fetchone('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            return int(row['id'])

        cursor = await self.db.execute(
            'INSERT INTO users (telegram_id, username, first_name, full_name, is_admin) VALUES (?, ?, ?, ?, ?)',
            (telegram_id, username, first_name, full_name, int(is_admin)),
        )
        user_id = int(cursor.lastrowid)
        await self.db.execute('INSERT OR IGNORE INTO brand_profiles (user_id) VALUES (?)', (user_id,))
        now = datetime.now(timezone.utc)
        await self.db.execute(
            '''
            INSERT OR IGNORE INTO subscriptions_stub (
                user_id, trial_started_at, trial_ends_at, subscription_status, is_payment_enabled
            ) VALUES (?, ?, ?, 'trial', 0)
            ''',
            (user_id, now.isoformat(), (now + timedelta(days=3)).isoformat()),
        )
        await self.db.execute(
            'INSERT OR IGNORE INTO referrals_stub (user_id, referral_code) VALUES (?, ?)',
            (user_id, f'ref{telegram_id}'),
        )
        return user_id

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.fetchone('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
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
        latest = await self.db.fetchall('SELECT first_name, full_name, created_at FROM users ORDER BY id DESC LIMIT 5')
        return {
            'users': int(users['cnt']) if users else 0,
            'active_users': int(active['cnt']) if active else 0,
            'generations': int(generations['cnt']) if generations else 0,
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
