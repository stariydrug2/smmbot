from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.db import Database
from database.product_repository import ProductRepository
from database.queries import QueryService
from config import Settings
from services.subscription_service import SubscriptionService


class ProductRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / 'test.sqlite3')
        await self.db.connect()
        await self.db.init_db()
        self.queries = QueryService(self.db)
        self.repository = ProductRepository(self.db)
        self.user_id = await self.queries.create_or_update_user(
            telegram_id=101,
            username='tester',
            first_name='Test',
            full_name='Test User',
            is_admin=False,
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_new_user_has_no_automatic_trial(self) -> None:
        subscription = await self.queries.get_user_subscription(self.user_id)
        trial = await self.repository.get_trial(self.user_id)

        self.assertEqual(subscription['status'], 'none')
        self.assertEqual(trial['status'], 'none')
        self.assertEqual(trial['generation_limit'], 0)

    async def test_legacy_trial_markers_are_migrated_to_none(self) -> None:
        await self.db.execute("UPDATE user_subscriptions SET status = 'trial' WHERE user_id = ?", (self.user_id,))
        await self.db.execute(
            "UPDATE subscriptions_stub SET subscription_status = 'trial' WHERE user_id = ?",
            (self.user_id,),
        )
        await self.db.execute('DELETE FROM schema_migrations WHERE version IN (1, 2)')

        await self.db._run_migrations()

        subscription = await self.queries.get_user_subscription(self.user_id)
        stub = await self.queries.get_subscription_stub(self.user_id)
        self.assertEqual(subscription['status'], 'none')
        self.assertEqual(stub['subscription_status'], 'none')

    async def test_old_examples_table_gets_channel_scope_migration(self) -> None:
        path = Path(self.temp_dir.name) / 'legacy.sqlite3'
        legacy = sqlite3.connect(path)
        legacy.executescript(
            '''
            CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL);
            CREATE TABLE user_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                example_text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            '''
        )
        legacy.close()

        migrated = Database(path)
        await migrated.connect()
        await migrated.init_db()
        columns = {row['name'] for row in await migrated.fetchall('PRAGMA table_info(user_examples)')}
        index = await migrated.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_user_examples_channel_id'"
        )
        await migrated.close()

        self.assertIn('channel_id', columns)
        self.assertIsNotNone(index)

    async def test_trial_reservation_can_be_refunded_and_committed(self) -> None:
        await self.repository.activate_trial(self.user_id, duration_hours=24, generation_limit=2)

        first = await self.repository.reserve_usage(self.user_id, 'post', 'posts_left', False)
        self.assertEqual(first['source'], 'trial')
        self.assertEqual((await self.repository.get_trial(self.user_id))['generation_used'], 1)

        self.assertTrue(await self.repository.refund_usage(first['id']))
        self.assertEqual((await self.repository.get_trial(self.user_id))['generation_used'], 0)

        second = await self.repository.reserve_usage(self.user_id, 'post', 'posts_left', False)
        self.assertTrue(await self.repository.commit_usage(second['id']))
        self.assertEqual((await self.repository.get_trial(self.user_id))['generation_used'], 1)
        self.assertFalse(await self.repository.refund_usage(second['id']))

    async def test_expired_paid_limit_is_not_consumed(self) -> None:
        await self.queries.add_user_limits(
            self.user_id,
            {'posts_left': 2},
            reset_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        reservation = await self.repository.reserve_usage(self.user_id, 'post', 'posts_left', False)
        self.assertIsNone(reservation)
        self.assertEqual((await self.queries.get_user_limits(self.user_id))['posts_left'], 2)

    async def test_draft_versions_and_atomic_schedule_claim(self) -> None:
        channel = await self.repository.connect_channel(
            user_id=self.user_id,
            telegram_chat_id=-100100,
            title='Test channel',
            username='test_channel',
            timezone_name='Europe/Moscow',
            bot_can_post=True,
            bot_can_edit=True,
        )
        draft = await self.repository.create_draft(
            self.user_id,
            int(channel['id']),
            'text',
            'brief',
            'version one',
            'post',
        )
        await self.repository.update_draft_text(int(draft['id']), self.user_id, 'version two', 'manual_edit')
        versions = await self.db.fetchall(
            'SELECT version_number, content_text FROM content_draft_versions WHERE draft_id = ? ORDER BY version_number',
            (int(draft['id']),),
        )
        self.assertEqual([(row['version_number'], row['content_text']) for row in versions], [(1, 'version one'), (2, 'version two')])

        schedule = await self.repository.create_schedule(
            int(draft['id']),
            self.user_id,
            int(channel['id']),
            (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        )
        claimed = await self.repository.claim_due_schedule(datetime.now(timezone.utc).isoformat())
        self.assertEqual(claimed['id'], schedule['id'])
        self.assertIsNone(await self.repository.claim_due_schedule(datetime.now(timezone.utc).isoformat()))

        second_draft = await self.repository.create_draft(
            self.user_id,
            int(channel['id']),
            'text',
            'brief two',
            'another draft',
            'post',
        )
        second_schedule = await self.repository.create_schedule(
            int(second_draft['id']),
            self.user_id,
            int(channel['id']),
            (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        self.assertTrue(await self.repository.cancel_schedule(int(second_schedule['id']), self.user_id))
        restored = await self.repository.get_draft(int(second_draft['id']), self.user_id)
        self.assertEqual(restored['status'], 'draft')

    async def test_payment_activation_is_idempotent(self) -> None:
        await self.queries.sync_subscription_plans([
            {
                'code': 'test',
                'title': 'Test',
                'duration_days': 30,
                'price_rub': 100,
                'limits': {'posts_left': 5},
                'is_active': True,
            }
        ])
        plan = await self.queries.get_plan_by_code('test')
        payment_id = await self.queries.create_payment(
            self.user_id,
            int(plan['id']),
            100,
            'Test',
            {},
        )
        service = SubscriptionService(self.queries, Settings())
        first = await service.activate_plan_from_payment(
            self.user_id,
            int(plan['id']),
            payment_id,
            provider_payload_json='{}',
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        second = await service.activate_plan_from_payment(
            self.user_id,
            int(plan['id']),
            payment_id,
            provider_payload_json='{}',
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual((await self.queries.get_user_limits(self.user_id))['posts_left'], 5)
        self.assertEqual((await self.queries.get_payment(payment_id))['status'], 'paid')
