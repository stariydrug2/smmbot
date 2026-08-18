from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database.db import Database
from database.queries import LIMIT_FIELDS


CHANNEL_PROFILE_FIELDS = {
    'niche',
    'project_description',
    'target_audience',
    'tone_of_voice',
    'post_length',
    'emoji_style',
    'heading_style',
    'products',
    'key_topics',
    'content_rubrics',
    'undesired_topics',
    'forbidden_phrases',
    'typical_cta',
    'goals',
    'additional_instructions',
    'visual_instructions',
    'is_complete',
}


class ProductRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_active_channel(self, user_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            "SELECT * FROM connected_channels WHERE owner_user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        return dict(row) if row else None

    async def get_channel(self, channel_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        query = 'SELECT * FROM connected_channels WHERE id = ?'
        params: list[Any] = [channel_id]
        if user_id is not None:
            query += ' AND owner_user_id = ?'
            params.append(user_id)
        row = await self.db.fetchone(query, params)
        return dict(row) if row else None

    async def get_channel_by_chat_id(self, telegram_chat_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            'SELECT * FROM connected_channels WHERE telegram_chat_id = ?',
            (telegram_chat_id,),
        )
        return dict(row) if row else None

    async def connect_channel(
        self,
        user_id: int,
        telegram_chat_id: int,
        title: str,
        username: str | None,
        timezone_name: str,
        bot_can_post: bool,
        bot_can_edit: bool,
    ) -> dict[str, Any]:
        existing = await self.get_channel_by_chat_id(telegram_chat_id)
        if existing and int(existing['owner_user_id']) != user_id:
            raise ValueError('Этот канал уже подключён к другому аккаунту KonturSMM.')

        async with self.db.transaction() as connection:
            await connection.execute(
                "UPDATE connected_channels SET status = 'inactive', updated_at = CURRENT_TIMESTAMP "
                "WHERE owner_user_id = ? AND telegram_chat_id != ? AND status = 'active'",
                (user_id, telegram_chat_id),
            )
            await connection.execute(
                '''
                INSERT INTO connected_channels (
                    owner_user_id, telegram_chat_id, username, title, status, timezone,
                    bot_can_post, bot_can_edit, connected_at, last_permissions_check_at,
                    disconnected_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(telegram_chat_id) DO UPDATE SET
                    username = excluded.username,
                    title = excluded.title,
                    status = 'active',
                    timezone = excluded.timezone,
                    bot_can_post = excluded.bot_can_post,
                    bot_can_edit = excluded.bot_can_edit,
                    last_permissions_check_at = CURRENT_TIMESTAMP,
                    disconnected_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (user_id, telegram_chat_id, username, title, timezone_name, int(bot_can_post), int(bot_can_edit)),
            )
        channel = await self.get_channel_by_chat_id(telegram_chat_id)
        if not channel:
            raise RuntimeError('Не удалось сохранить канал.')
        await self.ensure_channel_profile(int(channel['id']))
        return channel

    async def update_channel_permissions(self, channel_id: int, can_post: bool, can_edit: bool) -> None:
        await self.db.execute(
            '''
            UPDATE connected_channels
            SET bot_can_post = ?, bot_can_edit = ?, last_permissions_check_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (int(can_post), int(can_edit), channel_id),
        )

    async def update_channel_timezone(self, channel_id: int, user_id: int, timezone_name: str) -> bool:
        cursor = await self.db.execute(
            '''
            UPDATE connected_channels
            SET timezone = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND owner_user_id = ? AND status = 'active'
            ''',
            (timezone_name, channel_id, user_id),
        )
        return bool(cursor.rowcount)

    async def disconnect_channel(self, channel_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            '''
            UPDATE connected_channels
            SET status = 'disconnected', disconnected_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND owner_user_id = ? AND status = 'active'
            ''',
            (channel_id, user_id),
        )
        return bool(cursor.rowcount)

    async def ensure_channel_profile(self, channel_id: int) -> dict[str, Any]:
        await self.db.execute('INSERT OR IGNORE INTO channel_profiles (channel_id) VALUES (?)', (channel_id,))
        profile = await self.get_channel_profile(channel_id)
        return profile or {}

    async def get_channel_profile(self, channel_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone('SELECT * FROM channel_profiles WHERE channel_id = ?', (channel_id,))
        return dict(row) if row else None

    async def update_channel_profile(self, channel_id: int, **fields: Any) -> dict[str, Any]:
        clean = {key: value for key, value in fields.items() if key in CHANNEL_PROFILE_FIELDS}
        await self.ensure_channel_profile(channel_id)
        if clean:
            columns = ', '.join(f'{key} = ?' for key in clean)
            await self.db.execute(
                f'UPDATE channel_profiles SET {columns}, updated_at = CURRENT_TIMESTAMP WHERE channel_id = ?',
                [*clean.values(), channel_id],
            )
        return await self.ensure_channel_profile(channel_id)

    async def create_draft(
        self,
        user_id: int,
        channel_id: int | None,
        source_type: str,
        source_text: str,
        content_text: str,
        ai_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self.db.transaction() as connection:
            cursor = await connection.execute(
                '''
                INSERT INTO content_drafts (
                    user_id, channel_id, source_type, source_text, content_text, ai_mode, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (user_id, channel_id, source_type, source_text, content_text, ai_mode, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            draft_id = int(cursor.lastrowid)
            await connection.execute(
                '''
                INSERT INTO content_draft_versions (draft_id, version_number, content_text, change_type)
                VALUES (?, 1, ?, 'created')
                ''',
                (draft_id, content_text),
            )
        draft = await self.get_draft(draft_id, user_id)
        if not draft:
            raise RuntimeError('Не удалось сохранить черновик.')
        return draft

    async def get_draft(self, draft_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        query = 'SELECT * FROM content_drafts WHERE id = ?'
        params: list[Any] = [draft_id]
        if user_id is not None:
            query += ' AND user_id = ?'
            params.append(user_id)
        row = await self.db.fetchone(query, params)
        return dict(row) if row else None

    async def list_drafts(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM content_drafts WHERE user_id = ? AND status IN ('draft', 'approved', 'scheduled', 'review') "
            'ORDER BY updated_at DESC, id DESC LIMIT ?',
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def update_draft_text(self, draft_id: int, user_id: int, content_text: str, change_type: str) -> dict[str, Any] | None:
        async with self.db.transaction() as connection:
            row = await (await connection.execute(
                'SELECT id FROM content_drafts WHERE id = ? AND user_id = ?',
                (draft_id, user_id),
            )).fetchone()
            if not row:
                return None
            version_row = await (await connection.execute(
                'SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM content_draft_versions WHERE draft_id = ?',
                (draft_id,),
            )).fetchone()
            await connection.execute(
                'UPDATE content_drafts SET content_text = ?, status = \'draft\', updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (content_text, draft_id),
            )
            await connection.execute(
                'INSERT INTO content_draft_versions (draft_id, version_number, content_text, change_type) VALUES (?, ?, ?, ?)',
                (draft_id, int(version_row['next_version']), content_text, change_type),
            )
        return await self.get_draft(draft_id, user_id)

    async def set_draft_image(self, draft_id: int, user_id: int, file_id: str, prompt: str = '') -> bool:
        cursor = await self.db.execute(
            '''
            UPDATE content_drafts
            SET image_file_id = ?, image_prompt = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            ''',
            (file_id, prompt, draft_id, user_id),
        )
        return bool(cursor.rowcount)

    async def create_schedule(self, draft_id: int, user_id: int, channel_id: int, publish_at: str) -> dict[str, Any]:
        async with self.db.transaction() as connection:
            draft = await (await connection.execute(
                "SELECT id FROM content_drafts WHERE id = ? AND user_id = ? "
                "AND status IN ('draft', 'approved') AND (channel_id IS NULL OR channel_id = ?)",
                (draft_id, user_id, channel_id),
            )).fetchone()
            if not draft:
                raise ValueError('Черновик не найден, уже запланирован или относится к другому каналу.')
            channel = await (await connection.execute(
                "SELECT id FROM connected_channels WHERE id = ? AND owner_user_id = ? AND status = 'active'",
                (channel_id, user_id),
            )).fetchone()
            if not channel:
                raise ValueError('Активный канал не найден.')
            cursor = await connection.execute(
                '''
                INSERT INTO publication_schedules (draft_id, user_id, channel_id, publish_at)
                VALUES (?, ?, ?, ?)
                ''',
                (draft_id, user_id, channel_id, publish_at),
            )
            schedule_id = int(cursor.lastrowid)
            await connection.execute(
                "UPDATE content_drafts SET channel_id = ?, status = 'scheduled', approved_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (channel_id, draft_id),
            )
        row = await self.db.fetchone('SELECT * FROM publication_schedules WHERE id = ?', (schedule_id,))
        return dict(row)

    async def list_schedules(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            '''
            SELECT ps.*, cd.content_text, cc.title AS channel_title, cc.timezone
            FROM publication_schedules ps
            JOIN content_drafts cd ON cd.id = ps.draft_id
            JOIN connected_channels cc ON cc.id = ps.channel_id
            WHERE ps.user_id = ? AND ps.status IN ('scheduled', 'processing', 'failed', 'interrupted')
            ORDER BY ps.publish_at ASC LIMIT ?
            ''',
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def cancel_schedule(self, schedule_id: int, user_id: int) -> bool:
        async with self.db.transaction() as connection:
            row = await (await connection.execute(
                "SELECT draft_id FROM publication_schedules WHERE id = ? AND user_id = ? "
                "AND status IN ('scheduled', 'failed', 'interrupted')",
                (schedule_id, user_id),
            )).fetchone()
            if not row:
                return False
            await connection.execute(
                '''
                UPDATE publication_schedules
                SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (schedule_id,),
            )
            await connection.execute(
                "UPDATE content_drafts SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'scheduled'",
                (int(row['draft_id']),),
            )
        return True

    async def claim_due_schedule(self, now_iso: str) -> dict[str, Any] | None:
        async with self.db.transaction() as connection:
            row = await (await connection.execute(
                '''
                SELECT ps.id
                FROM publication_schedules ps
                WHERE ps.status IN ('scheduled', 'failed')
                  AND ps.publish_at <= ?
                  AND (ps.next_retry_at IS NULL OR ps.next_retry_at <= ?)
                ORDER BY ps.publish_at ASC, ps.id ASC
                LIMIT 1
                ''',
                (now_iso, now_iso),
            )).fetchone()
            if not row:
                return None
            cursor = await connection.execute(
                '''
                UPDATE publication_schedules
                SET status = 'processing', claimed_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('scheduled', 'failed')
                ''',
                (now_iso, int(row['id'])),
            )
            if not cursor.rowcount:
                return None
            claimed = await (await connection.execute(
                '''
                SELECT ps.*, cd.content_text, cd.image_file_id, cc.telegram_chat_id,
                       u.telegram_id,
                       cc.title AS channel_title, cc.bot_can_post
                FROM publication_schedules ps
                JOIN content_drafts cd ON cd.id = ps.draft_id
                JOIN connected_channels cc ON cc.id = ps.channel_id
                JOIN users u ON u.id = ps.user_id
                WHERE ps.id = ?
                ''',
                (int(row['id']),),
            )).fetchone()
        return dict(claimed) if claimed else None

    async def recover_stale_schedules(self, minutes: int = 15) -> int:
        cursor = await self.db.execute(
            '''
            UPDATE publication_schedules
            SET status = 'interrupted',
                error = 'Бот был перезапущен во время отправки. Проверьте канал перед повтором.',
                next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'processing' AND datetime(claimed_at) < datetime('now', ?)
            ''',
            (f'-{minutes} minutes',),
        )
        return int(cursor.rowcount or 0)

    async def recover_stale_draft_publications(self, minutes: int = 15) -> int:
        cursor = await self.db.execute(
            '''
            UPDATE content_drafts
            SET status = 'review', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'publishing' AND datetime(updated_at) < datetime('now', ?)
            ''',
            (f'-{minutes} minutes',),
        )
        return int(cursor.rowcount or 0)

    async def claim_draft_for_publication(self, draft_id: int, user_id: int) -> dict[str, Any] | None:
        async with self.db.transaction() as connection:
            cursor = await connection.execute(
                '''
                UPDATE content_drafts
                SET status = 'publishing', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ? AND status IN ('draft', 'approved')
                ''',
                (draft_id, user_id),
            )
            if not cursor.rowcount:
                return None
            row = await (await connection.execute('SELECT * FROM content_drafts WHERE id = ?', (draft_id,))).fetchone()
        return dict(row) if row else None

    async def release_draft_publication(self, draft_id: int, user_id: int) -> None:
        await self.db.execute(
            "UPDATE content_drafts SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ? AND status = 'publishing'",
            (draft_id, user_id),
        )

    async def complete_publication(
        self,
        draft_id: int,
        channel_id: int,
        message_ids: list[int],
        schedule_id: int | None = None,
    ) -> int:
        async with self.db.transaction() as connection:
            cursor = await connection.execute(
                '''
                INSERT INTO publications (schedule_id, draft_id, channel_id, telegram_message_ids_json)
                VALUES (?, ?, ?, ?)
                ''',
                (schedule_id, draft_id, channel_id, json.dumps(message_ids)),
            )
            publication_id = int(cursor.lastrowid)
            await connection.execute(
                "UPDATE content_drafts SET status = 'published', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (draft_id,),
            )
            if schedule_id is not None:
                await connection.execute(
                    "UPDATE publication_schedules SET status = 'published', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (schedule_id,),
                )
        return publication_id

    async def fail_schedule(self, schedule_id: int, error: str, retry_seconds: int, max_retries: int) -> None:
        row = await self.db.fetchone('SELECT retry_count FROM publication_schedules WHERE id = ?', (schedule_id,))
        retries = int(row['retry_count'] or 0) + 1 if row else max_retries + 1
        terminal = retries > max_retries
        next_retry = None if terminal else (datetime.now(timezone.utc) + timedelta(seconds=retry_seconds)).isoformat()
        async with self.db.transaction() as connection:
            schedule = await (await connection.execute(
                'SELECT draft_id FROM publication_schedules WHERE id = ?',
                (schedule_id,),
            )).fetchone()
            await connection.execute(
                '''
                UPDATE publication_schedules
                SET status = ?, error = ?, retry_count = ?, next_retry_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                ('error' if terminal else 'failed', error[:1000], retries, next_retry, schedule_id),
            )
            if terminal and schedule:
                await connection.execute(
                    "UPDATE content_drafts SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'scheduled'",
                    (int(schedule['draft_id']),),
                )

    async def save_channel_post(
        self,
        channel_id: int,
        telegram_message_id: int,
        content_text: str,
        published_at: str | None,
        source: str = 'telegram',
    ) -> None:
        await self.db.execute(
            '''
            INSERT INTO channel_posts (channel_id, telegram_message_id, content_text, source, published_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, telegram_message_id) DO UPDATE SET
                content_text = excluded.content_text,
                published_at = COALESCE(excluded.published_at, channel_posts.published_at)
            ''',
            (channel_id, telegram_message_id, content_text, source, published_at),
        )

    async def list_channel_posts(self, channel_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            'SELECT * FROM channel_posts WHERE channel_id = ? ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?',
            (channel_id, limit),
        )
        return [dict(row) for row in rows]

    async def add_competitor_source(
        self,
        user_id: int,
        username: str | None,
        source_url: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        existing = await self.db.fetchone(
            'SELECT * FROM competitor_sources WHERE user_id = ? AND source_url = ? LIMIT 1',
            (user_id, source_url),
        )
        if existing:
            await self.db.execute(
                'UPDATE competitor_sources SET enabled = 1, username = ?, title = COALESCE(?, title), '
                'last_error = NULL WHERE id = ?',
                (username, title, int(existing['id'])),
            )
            row = await self.db.fetchone('SELECT * FROM competitor_sources WHERE id = ?', (int(existing['id']),))
            await self.get_competitor_settings(user_id)
            return dict(row)
        cursor = await self.db.execute(
            '''
            INSERT INTO competitor_sources (user_id, username, source_url, title)
            VALUES (?, ?, ?, ?)
            ''',
            (user_id, username, source_url, title),
        )
        row = await self.db.fetchone('SELECT * FROM competitor_sources WHERE id = ?', (int(cursor.lastrowid),))
        await self.get_competitor_settings(user_id)
        return dict(row)

    async def list_competitor_sources(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            'SELECT * FROM competitor_sources WHERE user_id = ? AND enabled = 1 ORDER BY id DESC',
            (user_id,),
        )
        return [dict(row) for row in rows]

    async def remove_competitor_source(self, source_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            'UPDATE competitor_sources SET enabled = 0 WHERE id = ? AND user_id = ?',
            (source_id, user_id),
        )
        return bool(cursor.rowcount)

    async def get_competitor_source(self, source_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        query = 'SELECT * FROM competitor_sources WHERE id = ?'
        params: list[Any] = [source_id]
        if user_id is not None:
            query += ' AND user_id = ?'
            params.append(user_id)
        row = await self.db.fetchone(query, params)
        return dict(row) if row else None

    async def count_competitor_sources(self, user_id: int) -> int:
        row = await self.db.fetchone(
            'SELECT COUNT(*) AS cnt FROM competitor_sources WHERE user_id = ? AND enabled = 1',
            (user_id,),
        )
        return int(row['cnt']) if row else 0

    async def list_all_active_competitor_sources(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            '''
            SELECT cs.*, u.telegram_id
            FROM competitor_sources cs
            JOIN users u ON u.id = cs.user_id
            WHERE cs.enabled = 1 AND cs.username IS NOT NULL
            ORDER BY lower(cs.username), cs.id
            '''
        )
        return [dict(row) for row in rows]

    async def mark_competitor_source_checked(
        self,
        source_id: int,
        *,
        last_seen_post: str | None = None,
        title: str | None = None,
        error: str | None = None,
        initialized: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if error:
            await self.db.execute(
                '''
                UPDATE competitor_sources
                SET last_checked_at = ?, last_error = ?
                WHERE id = ?
                ''',
                (now, error[:1000], source_id),
            )
            return
        await self.db.execute(
            '''
            UPDATE competitor_sources
            SET last_checked_at = ?, last_success_at = ?, last_error = NULL,
                last_seen_post = COALESCE(?, last_seen_post),
                title = COALESCE(?, title),
                initialized_at = CASE WHEN ? THEN COALESCE(initialized_at, ?) ELSE initialized_at END
            WHERE id = ?
            ''',
            (now, now, last_seen_post, title, int(initialized), now, source_id),
        )

    async def upsert_competitor_post(
        self,
        source_id: int,
        external_post_id: str,
        post_url: str,
        content_text: str,
        views: int,
        reactions: int,
        published_at: str | None,
    ) -> tuple[dict[str, Any], bool]:
        existing = await self.db.fetchone(
            'SELECT id FROM competitor_posts WHERE source_id = ? AND external_post_id = ?',
            (source_id, external_post_id),
        )
        await self.db.execute(
            '''
            INSERT INTO competitor_posts (
                source_id, external_post_id, post_url, content_text, views, reactions, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, external_post_id) DO UPDATE SET
                post_url = excluded.post_url,
                content_text = excluded.content_text,
                views = excluded.views,
                reactions = excluded.reactions,
                published_at = COALESCE(excluded.published_at, competitor_posts.published_at),
                updated_at = CURRENT_TIMESTAMP
            ''',
            (source_id, external_post_id, post_url, content_text, views, reactions, published_at),
        )
        row = await self.db.fetchone(
            'SELECT * FROM competitor_posts WHERE source_id = ? AND external_post_id = ?',
            (source_id, external_post_id),
        )
        return dict(row), existing is None

    async def list_prior_competitor_views(
        self,
        source_id: int,
        external_post_id: str,
        limit: int = 12,
    ) -> list[int]:
        rows = await self.db.fetchall(
            '''
            SELECT views
            FROM competitor_posts
            WHERE source_id = ?
              AND external_post_id != ?
              AND views > 0
              AND CAST(external_post_id AS INTEGER) < CAST(? AS INTEGER)
            ORDER BY CAST(external_post_id AS INTEGER) DESC
            LIMIT ?
            ''',
            (source_id, external_post_id, external_post_id, limit),
        )
        return [int(row['views']) for row in rows]

    async def update_competitor_post_strength(
        self,
        post_id: int,
        score: float | None,
        is_strong: bool,
    ) -> tuple[dict[str, Any], bool]:
        existing = await self.db.fetchone('SELECT is_strong FROM competitor_posts WHERE id = ?', (post_id,))
        was_strong = bool(existing and existing['is_strong'])
        await self.db.execute(
            '''
            UPDATE competitor_posts
            SET strength_score = ?, is_strong = CASE WHEN is_strong = 1 OR ? = 1 THEN 1 ELSE 0 END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (score, int(is_strong), post_id),
        )
        row = await self.db.fetchone('SELECT * FROM competitor_posts WHERE id = ?', (post_id,))
        return dict(row), bool(is_strong and not was_strong)

    async def mark_competitor_post_notified(self, post_id: int, notification_type: str) -> None:
        column = {'new': 'notified_new_at', 'strong': 'notified_strong_at'}.get(notification_type)
        if not column:
            raise ValueError('Unknown competitor notification type')
        await self.db.execute(
            f'UPDATE competitor_posts SET {column} = COALESCE({column}, ?) WHERE id = ?',
            (datetime.now(timezone.utc).isoformat(), post_id),
        )

    async def get_competitor_post(self, post_id: int, user_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            '''
            SELECT cp.*, cs.user_id, cs.username, cs.title AS source_title, cs.source_url
            FROM competitor_posts cp
            JOIN competitor_sources cs ON cs.id = cp.source_id
            WHERE cp.id = ? AND cs.user_id = ? AND cs.enabled = 1
            ''',
            (post_id, user_id),
        )
        return dict(row) if row else None

    async def list_competitor_posts(
        self,
        user_id: int,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = '''
            SELECT cp.*, cs.username, cs.title AS source_title, cs.source_url
            FROM competitor_posts cp
            JOIN competitor_sources cs ON cs.id = cp.source_id
            WHERE cs.user_id = ? AND cs.enabled = 1
        '''
        params: list[Any] = [user_id]
        if since:
            query += ' AND COALESCE(cp.published_at, cp.first_seen_at) >= ?'
            params.append(since)
        query += ' ORDER BY COALESCE(cp.published_at, cp.first_seen_at) DESC LIMIT ?'
        params.append(limit)
        rows = await self.db.fetchall(query, params)
        return [dict(row) for row in rows]

    async def get_competitor_settings(self, user_id: int) -> dict[str, Any]:
        await self.db.execute(
            'INSERT OR IGNORE INTO competitor_monitor_settings (user_id) VALUES (?)',
            (user_id,),
        )
        row = await self.db.fetchone('SELECT * FROM competitor_monitor_settings WHERE user_id = ?', (user_id,))
        return dict(row)

    async def update_competitor_settings(self, user_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {
            'notify_mode',
            'pulse_enabled',
            'weekly_plan_enabled',
            'last_pulse_week',
            'last_plan_week',
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        await self.get_competitor_settings(user_id)
        if updates:
            assignments = ', '.join(f'{key} = ?' for key in updates)
            await self.db.execute(
                f'UPDATE competitor_monitor_settings SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                [*updates.values(), user_id],
            )
        return await self.get_competitor_settings(user_id)

    async def list_competitor_users(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            '''
            SELECT DISTINCT u.id AS user_id, u.telegram_id, u.username,
                COALESCE(cc.timezone, 'Europe/Moscow') AS timezone
            FROM users u
            JOIN competitor_sources cs ON cs.user_id = u.id AND cs.enabled = 1
            LEFT JOIN connected_channels cc ON cc.id = (
                SELECT id FROM connected_channels
                WHERE owner_user_id = u.id AND status = 'active'
                ORDER BY id DESC LIMIT 1
            )
            '''
        )
        return [dict(row) for row in rows]

    async def get_competitor_report(self, user_id: int, report_type: str, cache_key: str) -> str | None:
        row = await self.db.fetchone(
            '''
            SELECT content_text FROM competitor_reports
            WHERE user_id = ? AND report_type = ? AND cache_key = ?
            ''',
            (user_id, report_type, cache_key),
        )
        return str(row['content_text']) if row else None

    async def save_competitor_report(
        self,
        user_id: int,
        report_type: str,
        cache_key: str,
        content_text: str,
    ) -> None:
        await self.db.execute(
            '''
            INSERT INTO competitor_reports (user_id, report_type, cache_key, content_text)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, report_type, cache_key) DO UPDATE SET
                content_text = excluded.content_text
            ''',
            (user_id, report_type, cache_key, content_text),
        )

    async def get_trial(self, user_id: int) -> dict[str, Any]:
        await self.db.execute(
            "INSERT OR IGNORE INTO trial_access (user_id, status, generation_limit) VALUES (?, 'none', 0)",
            (user_id,),
        )
        row = await self.db.fetchone('SELECT * FROM trial_access WHERE user_id = ?', (user_id,))
        return dict(row)

    async def activate_trial(self, user_id: int, duration_hours: int, generation_limit: int) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(hours=duration_hours)
        async with self.db.transaction() as connection:
            await connection.execute(
                "INSERT OR IGNORE INTO trial_access (user_id, status, generation_limit) VALUES (?, 'none', 0)",
                (user_id,),
            )
            cursor = await connection.execute(
                '''
                UPDATE trial_access
                SET status = 'active', started_at = ?, ends_at = ?, generation_limit = ?,
                    generation_used = 0, used_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND status = 'none'
                ''',
                (now.isoformat(), ends_at.isoformat(), generation_limit, user_id),
            )
            if not cursor.rowcount:
                return None
        return await self.get_trial(user_id)

    async def mark_trial_membership_verified(self, user_id: int) -> None:
        await self.get_trial(user_id)
        await self.db.execute(
            'UPDATE trial_access SET membership_verified_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,),
        )

    async def clear_trial_membership_verification(self, user_id: int) -> None:
        await self.get_trial(user_id)
        await self.db.execute(
            'UPDATE trial_access SET membership_verified_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,),
        )

    async def refresh_trial_status(self, user_id: int, now_iso: str) -> dict[str, Any]:
        trial = await self.get_trial(user_id)
        if trial['status'] == 'active':
            if trial.get('ends_at') and str(trial['ends_at']) <= now_iso:
                await self.db.execute(
                    "UPDATE trial_access SET status = 'expired', updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'",
                    (user_id,),
                )
            elif int(trial.get('generation_used') or 0) >= int(trial.get('generation_limit') or 0):
                await self.db.execute(
                    "UPDATE trial_access SET status = 'used', used_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'",
                    (user_id,),
                )
        return await self.get_trial(user_id)

    async def reserve_usage(
        self,
        user_id: int,
        feature: str,
        limit_field: str | None,
        is_admin: bool,
        unlimited_source: str | None = None,
    ) -> dict[str, Any] | None:
        if limit_field is not None and limit_field not in LIMIT_FIELDS:
            raise ValueError(f'Unknown limit field: {limit_field}')
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.transaction() as connection:
            source: str | None = None
            if is_admin:
                source = 'admin'
            elif unlimited_source:
                source = unlimited_source
            else:
                trial = await (await connection.execute(
                    'SELECT * FROM trial_access WHERE user_id = ?',
                    (user_id,),
                )).fetchone()
                if trial and trial['status'] == 'active':
                    if trial['ends_at'] and str(trial['ends_at']) <= now:
                        await connection.execute(
                            "UPDATE trial_access SET status = 'expired', updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                            (user_id,),
                        )
                    elif int(trial['generation_used'] or 0) < int(trial['generation_limit'] or 0):
                        await connection.execute(
                            'UPDATE trial_access SET generation_used = generation_used + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                            (user_id,),
                        )
                        source = 'trial'

                if source is None and limit_field:
                    await connection.execute('INSERT OR IGNORE INTO user_limits (user_id) VALUES (?)', (user_id,))
                    cursor = await connection.execute(
                        f'''
                        UPDATE user_limits
                        SET {limit_field} = {limit_field} - 1, updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                          AND COALESCE({limit_field}, 0) > 0
                          AND (reset_at IS NULL OR reset_at > ?)
                        ''',
                        (user_id, now),
                    )
                    if cursor.rowcount:
                        source = 'paid'

            if source is None:
                return None
            cursor = await connection.execute(
                '''
                INSERT INTO usage_reservations (user_id, feature, source, limit_field)
                VALUES (?, ?, ?, ?)
                ''',
                (user_id, feature, source, limit_field),
            )
            reservation_id = int(cursor.lastrowid)
        return {'id': reservation_id, 'source': source, 'feature': feature, 'limit_field': limit_field}

    async def commit_usage(self, reservation_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE usage_reservations SET status = 'committed', committed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'reserved'",
            (reservation_id,),
        )
        if not cursor.rowcount:
            return False
        row = await self.db.fetchone('SELECT user_id, source FROM usage_reservations WHERE id = ?', (reservation_id,))
        if row and row['source'] == 'trial':
            trial = await self.get_trial(int(row['user_id']))
            if int(trial.get('generation_used') or 0) >= int(trial.get('generation_limit') or 0):
                await self.db.execute(
                    "UPDATE trial_access SET status = 'used', used_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'",
                    (int(row['user_id']),),
                )
        return True

    async def refund_usage(self, reservation_id: int) -> bool:
        async with self.db.transaction() as connection:
            row = await (await connection.execute(
                "SELECT * FROM usage_reservations WHERE id = ? AND status = 'reserved'",
                (reservation_id,),
            )).fetchone()
            if not row:
                return False
            if row['source'] == 'trial':
                await connection.execute(
                    'UPDATE trial_access SET generation_used = MAX(0, generation_used - 1), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                    (int(row['user_id']),),
                )
            elif row['source'] == 'paid' and row['limit_field'] in LIMIT_FIELDS:
                await connection.execute(
                    f'UPDATE user_limits SET {row["limit_field"]} = {row["limit_field"]} + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                    (int(row['user_id']),),
                )
            await connection.execute(
                "UPDATE usage_reservations SET status = 'refunded', refunded_at = CURRENT_TIMESTAMP WHERE id = ?",
                (reservation_id,),
            )
        return True

    async def recover_stale_usage(self, minutes: int = 20) -> int:
        rows = await self.db.fetchall(
            "SELECT id FROM usage_reservations WHERE status = 'reserved' AND created_at < datetime('now', ?)",
            (f'-{minutes} minutes',),
        )
        recovered = 0
        for row in rows:
            recovered += int(await self.refund_usage(int(row['id'])))
        return recovered

    async def log_activity(
        self,
        event_name: str,
        user_id: int | None = None,
        telegram_id: int | None = None,
        username: str | None = None,
        full_name: str | None = None,
        payload: dict[str, Any] | None = None,
        event_type: str = 'outcome',
    ) -> None:
        await self.db.execute(
            '''
            INSERT INTO user_activity_events (
                user_id, telegram_id, username, full_name, event_type, event_name, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (user_id, telegram_id, username, full_name, event_type, event_name, json.dumps(payload or {}, ensure_ascii=False)),
        )

    async def get_results(self, user_id: int) -> dict[str, int]:
        drafts = await self.db.fetchone('SELECT COUNT(*) AS cnt FROM content_drafts WHERE user_id = ?', (user_id,))
        published = await self.db.fetchone(
            'SELECT COUNT(*) AS cnt FROM publications p JOIN content_drafts d ON d.id = p.draft_id WHERE d.user_id = ?',
            (user_id,),
        )
        scheduled = await self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM publication_schedules "
            "WHERE user_id = ? AND status IN ('scheduled', 'failed', 'interrupted')",
            (user_id,),
        )
        analyses = await self.db.fetchone('SELECT COUNT(*) AS cnt FROM analyses WHERE user_id = ?', (user_id,))
        generations = await self.db.fetchone('SELECT COUNT(*) AS cnt FROM generation_history WHERE user_id = ?', (user_id,))
        competitor_sources = await self.db.fetchone(
            'SELECT COUNT(*) AS cnt FROM competitor_sources WHERE user_id = ? AND enabled = 1',
            (user_id,),
        )
        competitor_posts = await self.db.fetchone(
            '''
            SELECT COUNT(*) AS cnt
            FROM competitor_posts cp
            JOIN competitor_sources cs ON cs.id = cp.source_id
            WHERE cs.user_id = ? AND cs.enabled = 1
            ''',
            (user_id,),
        )
        strong_signals = await self.db.fetchone(
            '''
            SELECT COUNT(*) AS cnt
            FROM competitor_posts cp
            JOIN competitor_sources cs ON cs.id = cp.source_id
            WHERE cs.user_id = ? AND cs.enabled = 1 AND cp.is_strong = 1
            ''',
            (user_id,),
        )
        return {
            'drafts': int(drafts['cnt']) if drafts else 0,
            'published': int(published['cnt']) if published else 0,
            'scheduled': int(scheduled['cnt']) if scheduled else 0,
            'analyses': int(analyses['cnt']) if analyses else 0,
            'generations': int(generations['cnt']) if generations else 0,
            'competitor_sources': int(competitor_sources['cnt']) if competitor_sources else 0,
            'competitor_posts': int(competitor_posts['cnt']) if competitor_posts else 0,
            'strong_signals': int(strong_signals['cnt']) if strong_signals else 0,
        }
