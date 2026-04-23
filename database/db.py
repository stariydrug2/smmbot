from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

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
        cursor = await self.connection.execute(query, tuple(params))
        await self.connection.commit()
        return cursor

    async def executescript(self, query: str) -> None:
        if not self.connection:
            raise RuntimeError('Database is not connected')
        await self.connection.executescript(query)
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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            full_name TEXT,
            is_subscribed INTEGER DEFAULT 0,
            is_onboarding_completed INTEGER DEFAULT 0,
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
            example_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
            subscription_status TEXT DEFAULT 'trial',
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
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            plan_id INTEGER,
            status TEXT NOT NULL DEFAULT 'trial',
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

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_user_id ON generation_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_created_at ON generation_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_examples_user_id ON user_examples(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id ON user_subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subscription_notifications_subscription_id ON subscription_notifications(subscription_id);
        """
        await self.executescript(schema)
        await self._run_migrations()
        logger.info('Database schema initialized')

    async def _run_migrations(self) -> None:
        migration_sql = """
        ALTER TABLE payments ADD COLUMN invoice_url TEXT;
        ALTER TABLE payments ADD COLUMN invoice_external_id TEXT;
        ALTER TABLE payments ADD COLUMN description TEXT;
        """
        for statement in [line.strip() for line in migration_sql.split(';') if line.strip()]:
            try:
                await self.execute(statement)
            except Exception:
                continue
