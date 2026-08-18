from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from database.db import Database
from database.product_repository import ProductRepository
from database.queries import QueryService
from services.competitor_service import (
    CompetitorFeedError,
    CompetitorMonitoringService,
    PublicChannelPost,
    PublicChannelSnapshot,
    TelegramPublicFeedClient,
)


class TelegramPublicFeedParserTests(unittest.TestCase):
    def test_public_preview_is_parsed(self) -> None:
        html = '''
        <html><head><meta property="og:title" content="Market Radar"></head><body>
          <div class="tgme_widget_message" data-post="market_radar/101">
            <div class="tgme_widget_message_text">Первая <b>тема</b></div>
            <span class="tgme_widget_message_views">1.2K</span>
            <span class="tgme_reaction_value">34</span>
            <a class="tgme_widget_message_date" href="https://t.me/market_radar/101">
              <time datetime="2026-08-18T08:00:00+00:00"></time>
            </a>
          </div>
        </body></html>
        '''
        snapshot = TelegramPublicFeedClient.parse('market_radar', html)

        self.assertEqual(snapshot.title, 'Market Radar')
        self.assertEqual(len(snapshot.posts), 1)
        self.assertEqual(snapshot.posts[0].external_id, '101')
        self.assertEqual(snapshot.posts[0].text, 'Первая\nтема')
        self.assertEqual(snapshot.posts[0].views, 1200)
        self.assertEqual(snapshot.posts[0].reactions, 34)

    def test_source_links_are_normalized(self) -> None:
        self.assertEqual(CompetitorMonitoringService.normalize_source('@market_radar'), 'market_radar')
        self.assertEqual(
            CompetitorMonitoringService.normalize_source('https://t.me/s/market_radar/101'),
            'market_radar',
        )
        self.assertEqual(TelegramPublicFeedClient.parse_metric('2.07M'), 2_070_000)

    def test_contact_page_is_not_accepted_as_public_channel(self) -> None:
        html = '<html><head><meta property="og:title" content="Telegram: Contact @private"></head></html>'
        with self.assertRaises(CompetitorFeedError):
            TelegramPublicFeedClient.parse('private', html)


class CompetitorMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / 'competitors.sqlite3')
        await self.db.connect()
        await self.db.init_db()
        self.queries = QueryService(self.db)
        self.repository = ProductRepository(self.db)
        self.user_id = await self.queries.create_or_update_user(
            telegram_id=303,
            username='radar_user',
            first_name='Radar',
            full_name='Radar User',
            is_admin=False,
        )
        self.service = CompetitorMonitoringService(
            repository=self.repository,
            queries=self.queries,
            content_service=None,  # type: ignore[arg-type]
            usage_service=None,  # type: ignore[arg-type]
            settings=Settings(),
        )

    async def asyncTearDown(self) -> None:
        await self.service.close()
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_initial_posts_are_seeded_and_next_outlier_is_strong(self) -> None:
        source = await self.repository.add_competitor_source(
            self.user_id,
            'market_radar',
            'https://t.me/market_radar',
            'Market Radar',
        )
        published = datetime.now(timezone.utc).isoformat()
        initial = PublicChannelSnapshot(
            username='market_radar',
            title='Market Radar',
            posts=[
                PublicChannelPost(str(index), f'https://t.me/market_radar/{index}', f'Post {index}', 100, 0, published)
                for index in range(1, 7)
            ],
        )
        seeded = await self.service._ingest_source(source, initial, bot=None, allow_notifications=False)
        self.assertEqual(seeded.seeded_posts, 6)
        self.assertEqual(seeded.new_posts, 0)

        source = await self.repository.get_competitor_source(int(source['id']))
        next_snapshot = PublicChannelSnapshot(
            username='market_radar',
            title='Market Radar',
            posts=[
                *initial.posts,
                PublicChannelPost('7', 'https://t.me/market_radar/7', 'Strong post', 200, 12, published),
            ],
        )
        result = await self.service._ingest_source(source, next_snapshot, bot=None, allow_notifications=False)
        posts = await self.repository.list_competitor_posts(self.user_id)
        strong = next(item for item in posts if item['external_post_id'] == '7')

        self.assertEqual(result.new_posts, 1)
        self.assertEqual(result.strong_posts, 1)
        self.assertEqual(strong['is_strong'], 1)
        self.assertAlmostEqual(strong['strength_score'], 2.0)

    async def test_monitor_settings_are_persistent(self) -> None:
        defaults = await self.repository.get_competitor_settings(self.user_id)
        self.assertEqual(defaults['notify_mode'], 'strong')
        self.assertEqual(defaults['pulse_enabled'], 1)
        self.assertEqual(defaults['weekly_plan_enabled'], 0)

        updated = await self.repository.update_competitor_settings(
            self.user_id,
            notify_mode='all',
            weekly_plan_enabled=1,
        )
        self.assertEqual(updated['notify_mode'], 'all')
        self.assertEqual(updated['weekly_plan_enabled'], 1)

        await self.repository.save_competitor_report(self.user_id, 'pulse', 'same-posts', 'Cached pulse')
        self.assertEqual(
            await self.repository.get_competitor_report(self.user_id, 'pulse', 'same-posts'),
            'Cached pulse',
        )

    async def test_legacy_sources_receive_monitoring_columns(self) -> None:
        path = Path(self.temp_dir.name) / 'legacy_competitors.sqlite3'
        legacy = sqlite3.connect(path)
        legacy.executescript(
            '''
            CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL);
            CREATE TABLE competitor_sources (
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
                last_checked_at TEXT
            );
            '''
        )
        legacy.close()

        migrated = Database(path)
        await migrated.connect()
        await migrated.init_db()
        columns = {row['name'] for row in await migrated.fetchall('PRAGMA table_info(competitor_sources)')}
        posts_table = await migrated.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'competitor_posts'"
        )
        reports_table = await migrated.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'competitor_reports'"
        )
        await migrated.close()

        self.assertTrue({'initialized_at', 'last_success_at', 'last_error'}.issubset(columns))
        self.assertIsNotNone(posts_table)
        self.assertIsNotNone(reports_table)


if __name__ == '__main__':
    unittest.main()
