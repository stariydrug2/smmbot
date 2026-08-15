from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute('PRAGMA foreign_keys = ON;')
        await self.connection.execute('PRAGMA journal_mode = WAL;')
        await self.connection.commit()
        logger.info('Database connected: %s', self.db_path)

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()

    async def execute(self, query: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        async with self._write_lock:
            cursor = await self.connection.execute(query, tuple(params))
            await self.connection.commit()
            return cursor

    async def executescript(self, query: str) -> None:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        async with self._write_lock:
            await self.connection.executescript(query)
            await self.connection.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        async with self._write_lock:
            await self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self.connection
            except Exception:
                await self.connection.rollback()
                raise
            else:
                await self.connection.commit()

    async def fetchone(self, query: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        async with self.connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, query: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        async with self.connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchall()

    async def init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            full_name TEXT,
            is_subscribed INTEGER DEFAULT 0,
            is_onboarding_completed INTEGER DEFAULT 0,
            source TEXT DEFAULT 'direct',
            utm_source TEXT,
            utm_campaign TEXT,
            used_free_analysis INTEGER DEFAULT 0,
            current_tariff TEXT,
            tariff_started_at TEXT,
            tariff_expires_at TEXT,
            is_premium INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS brand_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            person_name TEXT,
            brand_name TEXT,
            brand_description TEXT,
            usage_goal TEXT,
            target_audience TEXT,
            tone_of_voice TEXT,
            post_length TEXT,
            preferred_formats TEXT,
            forbidden_words TEXT,
            wants_images INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            example_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS brand_memory_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            summary_text TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS generation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            generation_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            input_text TEXT,
            output_text TEXT,
            metadata_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS subscriptions_stub (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            trial_started_at TEXT,
            trial_ends_at TEXT,
            subscription_status TEXT DEFAULT 'none',
            is_payment_enabled INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS referrals_stub (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            referral_code TEXT,
            invited_by INTEGER,
            invited_count INTEGER DEFAULT 0,
            bonus_generations INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscription_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            price_rub INTEGER NOT NULL,
            plan_type TEXT DEFAULT 'subscription_30_days',
            description TEXT,
            limits_json TEXT,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            plan_id INTEGER,
            status TEXT NOT NULL DEFAULT 'none',
            starts_at TEXT,
            ends_at TEXT,
            auto_renew INTEGER DEFAULT 0,
            last_payment_id INTEGER,
            reminder_sent_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE SET NULL,
            FOREIGN KEY (last_payment_id) REFERENCES payments(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            provider TEXT NOT NULL DEFAULT 'robokassa',
            payment_mode TEXT NOT NULL DEFAULT 'generated_invoice',
            invoice_id INTEGER,
            provider_invoice_id TEXT,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            payment_url TEXT,
            invoice_url TEXT,
            invoice_external_id TEXT,
            description TEXT,
            shp_payload_json TEXT,
            provider_payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            paid_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS user_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            posts_left INTEGER DEFAULT 0,
            cta_left INTEGER DEFAULT 0,
            ideas_left INTEGER DEFAULT 0,
            improvements_left INTEGER DEFAULT 0,
            images_left INTEGER DEFAULT 0,
            voice_posts_left INTEGER DEFAULT 0,
            content_plans_left INTEGER DEFAULT 0,
            channel_reviews_left INTEGER DEFAULT 0,
            manual_post_reviews_left INTEGER DEFAULT 0,
            reset_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_text TEXT NOT NULL,
            post_goal TEXT,
            score INTEGER,
            result_text TEXT NOT NULL,
            is_free INTEGER DEFAULT 1,
            posts_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS manual_review_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            request_type TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            admin_response TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS subscription_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subscription_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
            UNIQUE (subscription_id, notification_type)
        );

        CREATE TABLE IF NOT EXISTS connected_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            telegram_chat_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
            bot_can_post INTEGER NOT NULL DEFAULT 0,
            bot_can_edit INTEGER NOT NULL DEFAULT 0,
            connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_permissions_check_at TEXT,
            disconnected_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS channel_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER UNIQUE NOT NULL,
            niche TEXT,
            project_description TEXT,
            target_audience TEXT,
            tone_of_voice TEXT,
            post_length TEXT,
            emoji_style TEXT,
            heading_style TEXT,
            products TEXT,
            key_topics TEXT,
            content_rubrics TEXT,
            undesired_topics TEXT,
            forbidden_phrases TEXT,
            typical_cta TEXT,
            goals TEXT,
            additional_instructions TEXT,
            visual_instructions TEXT,
            is_complete INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS content_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            source_type TEXT NOT NULL,
            source_text TEXT,
            content_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            ai_mode TEXT,
            image_file_id TEXT,
            image_prompt TEXT,
            metadata_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS content_draft_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            content_text TEXT NOT NULL,
            change_type TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (draft_id) REFERENCES content_drafts(id) ON DELETE CASCADE,
            UNIQUE (draft_id, version_number)
        );

        CREATE TABLE IF NOT EXISTS publication_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            publish_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            claimed_at TEXT,
            cancelled_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (draft_id) REFERENCES content_drafts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            draft_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            telegram_message_ids_json TEXT,
            status TEXT NOT NULL DEFAULT 'published',
            error TEXT,
            published_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES publication_schedules(id) ON DELETE SET NULL,
            FOREIGN KEY (draft_id) REFERENCES content_drafts(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS trial_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'none',
            started_at TEXT,
            ends_at TEXT,
            generation_limit INTEGER NOT NULL DEFAULT 0,
            generation_used INTEGER NOT NULL DEFAULT 0,
            used_at TEXT,
            membership_verified_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS usage_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            feature TEXT NOT NULL,
            source TEXT NOT NULL,
            limit_field TEXT,
            status TEXT NOT NULL DEFAULT 'reserved',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            committed_at TEXT,
            refunded_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS channel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            content_text TEXT,
            source TEXT NOT NULL DEFAULT 'telegram',
            published_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES connected_channels(id) ON DELETE CASCADE,
            UNIQUE (channel_id, telegram_message_id)
        );

        CREATE TABLE IF NOT EXISTS competitor_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            username TEXT,
            source_url TEXT,
            title TEXT,
            source_type TEXT NOT NULL DEFAULT 'telegram',
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_post TEXT,
            last_checked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            telegram_id INTEGER,
            username TEXT,
            full_name TEXT,
            event_type TEXT NOT NULL,
            event_name TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_user_id ON generation_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_created_at ON generation_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_examples_user_id ON user_examples(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id ON user_subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subscription_notifications_subscription_id ON subscription_notifications(subscription_id);
        CREATE INDEX IF NOT EXISTS idx_user_limits_user_id ON user_limits(user_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id);
        CREATE INDEX IF NOT EXISTS idx_manual_review_requests_status ON manual_review_requests(status);
        CREATE INDEX IF NOT EXISTS idx_connected_channels_owner ON connected_channels(owner_user_id, status);
        CREATE INDEX IF NOT EXISTS idx_content_drafts_user ON content_drafts(user_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_publication_schedules_due ON publication_schedules(status, publish_at, next_retry_at);
        CREATE INDEX IF NOT EXISTS idx_publications_channel ON publications(channel_id, published_at);
        CREATE INDEX IF NOT EXISTS idx_usage_reservations_user ON usage_reservations(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_channel_posts_channel ON channel_posts(channel_id, published_at);
        CREATE INDEX IF NOT EXISTS idx_competitor_sources_user ON competitor_sources(user_id, enabled);
        CREATE INDEX IF NOT EXISTS idx_user_activity_telegram_id ON user_activity_events(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_activity_event_name ON user_activity_events(event_name);
        """
        await self.executescript(schema)
        await self._run_migrations()
        logger.info('Database schema initialized')

    async def _run_migrations(self) -> None:
        await self._add_column_if_missing('payments', 'invoice_url', 'TEXT')
        await self._add_column_if_missing('payments', 'invoice_external_id', 'TEXT')
        await self._add_column_if_missing('payments', 'description', 'TEXT')
        await self._add_column_if_missing('users', 'source', "TEXT DEFAULT 'direct'")
        await self._add_column_if_missing('users', 'utm_source', 'TEXT')
        await self._add_column_if_missing('users', 'utm_campaign', 'TEXT')
        await self._add_column_if_missing('users', 'used_free_analysis', 'INTEGER DEFAULT 0')
        await self._add_column_if_missing('users', 'current_tariff', 'TEXT')
        await self._add_column_if_missing('users', 'tariff_started_at', 'TEXT')
        await self._add_column_if_missing('users', 'tariff_expires_at', 'TEXT')
        await self._add_column_if_missing('users', 'is_premium', 'INTEGER DEFAULT 0')
        await self._add_column_if_missing('subscription_plans', 'plan_type', "TEXT DEFAULT 'subscription_30_days'")
        await self._add_column_if_missing('subscription_plans', 'description', 'TEXT')
        await self._add_column_if_missing('subscription_plans', 'limits_json', 'TEXT')
        await self._add_column_if_missing('analyses', 'posts_count', 'INTEGER DEFAULT 1')
        await self._add_column_if_missing('user_examples', 'channel_id', 'INTEGER')
        await self.execute('CREATE INDEX IF NOT EXISTS idx_user_examples_channel_id ON user_examples(channel_id)')
        delivered_added = await self._add_column_if_missing('analyses', 'delivered_at', 'TEXT')
        if delivered_added:
            await self.execute('UPDATE analyses SET delivered_at = created_at WHERE delivered_at IS NULL')

        await self._apply_migration(
            1,
            """
            UPDATE user_subscriptions
            SET status = 'none', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'trial'
              AND plan_id IS NULL
              AND last_payment_id IS NULL;
            """,
        )
        await self._apply_migration(
            2,
            "UPDATE subscriptions_stub SET subscription_status = 'none' WHERE subscription_status = 'trial'",
        )
        await self.execute(
            'CREATE INDEX IF NOT EXISTS idx_analyses_delivery ON analyses(user_id, is_free, delivered_at)'
        )

    async def _add_column_if_missing(self, table: str, column: str, definition: str) -> bool:
        columns = {str(row['name']) for row in await self.fetchall(f'PRAGMA table_info({table})')}
        if column in columns:
            return False
        await self.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        logger.info('Migration added %s.%s', table, column)
        return True

    async def _apply_migration(self, version: int, sql: str) -> None:
        existing = await self.fetchone('SELECT version FROM schema_migrations WHERE version = ?', (version,))
        if existing:
            return
        async with self.transaction() as connection:
            # Versioned migrations are intentionally one statement each. Using
            # executescript here would make SQLite commit the surrounding
            # transaction implicitly.
            await connection.execute(sql.strip().rstrip(';'))
            await connection.execute('INSERT INTO schema_migrations (version) VALUES (?)', (version,))
        logger.info('Applied schema migration %s', version)
