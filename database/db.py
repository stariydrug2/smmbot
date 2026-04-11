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

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_user_id ON generation_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_generation_history_created_at ON generation_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_examples_user_id ON user_examples(user_id);
        """
        assert self.connection is not None
        await self.connection.executescript(schema)
        await self.connection.commit()
        logger.info('Database schema initialized')
