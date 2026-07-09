from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from database.queries import QueryService

logger = logging.getLogger(__name__)


class ActivityMiddleware(BaseMiddleware):
    """Logs lightweight user activity for admin analytics.

    The middleware never blocks the main handler: any logging error is written to
    logs and ignored. It intentionally stores only compact event data, not full
    conversations or generated content.
    """

    def __init__(self, queries: QueryService) -> None:
        self.queries = queries
        self._schema_ready = False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            await self._log_event(event)
        except Exception:
            logger.exception('Activity logging failed')
        return await handler(event, data)

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        await self.queries.db.execute(
            '''
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
            )
            '''
        )
        await self.queries.db.execute(
            'CREATE INDEX IF NOT EXISTS idx_user_activity_telegram_id ON user_activity_events(telegram_id)'
        )
        await self.queries.db.execute(
            'CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity_events(created_at)'
        )
        await self.queries.db.execute(
            'CREATE INDEX IF NOT EXISTS idx_user_activity_event_name ON user_activity_events(event_name)'
        )
        self._schema_ready = True

    async def _log_event(self, event: TelegramObject) -> None:
        extracted = await self._extract_event(event)
        if not extracted:
            return

        await self._ensure_schema()
        telegram_id = extracted['telegram_id']
        user = await self.queries.get_user_by_telegram_id(telegram_id) if telegram_id else None
        user_id = int(user['id']) if user and user.get('id') else None

        # If user is already registered but still not subscribed to the channel,
        # mark this as a funnel point. This helps spot users stuck at subscription.
        if user and not bool(user.get('is_subscribed')) and extracted['event_name'] not in {
            'start_opened',
            'subscription_check_clicked',
        }:
            extracted['event_name'] = 'subscription_gate_reached'

        await self.queries.db.execute(
            '''
            INSERT INTO user_activity_events (
                user_id, telegram_id, username, full_name, event_type, event_name, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                user_id,
                telegram_id,
                extracted.get('username'),
                extracted.get('full_name'),
                extracted['event_type'],
                extracted['event_name'],
                json.dumps(extracted.get('payload') or {}, ensure_ascii=False),
            ),
        )

    async def _extract_event(self, event: TelegramObject) -> dict[str, Any] | None:
        if isinstance(event, Message) and event.from_user:
            text = (event.text or event.caption or '').strip()
            return {
                'telegram_id': event.from_user.id,
                'username': event.from_user.username,
                'full_name': event.from_user.full_name,
                'event_type': 'message',
                'event_name': self._classify_message(event, text),
                'payload': self._message_payload(event, text),
            }

        if isinstance(event, CallbackQuery) and event.from_user:
            data = event.data or ''
            return {
                'telegram_id': event.from_user.id,
                'username': event.from_user.username,
                'full_name': event.from_user.full_name,
                'event_type': 'callback',
                'event_name': self._classify_callback(data),
                'payload': {'callback_data': data[:200]},
            }

        return None

    @staticmethod
    def _message_payload(message: Message, text: str) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if text:
            payload['text_preview'] = text[:250]
        if message.voice:
            payload['media'] = 'voice'
        elif message.audio:
            payload['media'] = 'audio'
        elif message.photo:
            payload['media'] = 'photo'
        elif message.document:
            payload['media'] = 'document'
        return payload

    @staticmethod
    def _classify_message(message: Message, text: str) -> str:
        lower = text.lower()

        if message.voice or message.audio:
            return 'voice_sent'
        if message.photo:
            return 'photo_sent'
        if message.document:
            return 'document_sent'

        if lower.startswith('/start'):
            return 'start_opened'
        if lower.startswith('/admin'):
            return 'admin_opened'
        if lower.startswith('/grant_access'):
            return 'admin_grant_access_command'
        if lower.startswith('/revoke_access'):
            return 'admin_revoke_access_command'
        if lower.startswith('/broadcast'):
            return 'admin_broadcast_command'
        if lower.startswith('/users'):
            return 'admin_users_command'
        if lower.startswith('/user '):
            return 'admin_user_lookup_command'
        if lower.startswith('/events'):
            return 'admin_events_command'
        if lower.startswith('/funnel'):
            return 'admin_funnel_command'

        if 'админка' in lower:
            return 'admin_opened'
        if 'подписка' in lower:
            return 'subscription_section_opened'
        if 'создать контент' in lower:
            return 'content_create_opened'
        if 'контент-план' in lower:
            return 'content_plan_opened'
        if 'пост из голосового' in lower or 'голос' in lower:
            return 'voice_mode_opened'
        if 'фото' in lower or 'визуал' in lower:
            return 'visual_mode_opened'
        if 'личный кабинет' in lower:
            return 'profile_opened'
        if 'история' in lower:
            return 'history_opened'
        if 'поддержка' in lower or 'помощь' in lower:
            return 'support_opened'
        if 'идея поста' in lower:
            return 'generation_mode_idea_selected'
        if 'готовый пост' in lower:
            return 'generation_mode_post_selected'
        if 'серия постов' in lower:
            return 'generation_mode_series_selected'
        if 'рерайт' in lower:
            return 'generation_mode_rewrite_selected'
        if lower == 'cta' or ' cta' in lower:
            return 'generation_mode_cta_selected'
        if 'story' in lower or 'анонс' in lower:
            return 'generation_mode_story_selected'

        return 'message_sent'

    @staticmethod
    def _classify_callback(data: str) -> str:
        if data == 'check_subscription':
            return 'subscription_check_clicked'
        if data == 'go:menu':
            return 'menu_opened'
        if data.startswith('content:'):
            return f"content_action_{data.split(':', 1)[1]}"
        if data.startswith('voice:'):
            return f"voice_action_{data.split(':', 1)[1]}"
        if data.startswith('photo:'):
            return f"photo_action_{data.split(':', 1)[1]}"
        if data.startswith('visual:'):
            return f"visual_action_{data.split(':', 1)[1]}"
        if data.startswith('history:view'):
            return 'history_record_viewed'
        if data.startswith('history:delete'):
            return 'history_record_deleted'
        if data.startswith('profile:'):
            return f"profile_action_{data.split(':', 1)[1]}"
        if data.startswith('payment:manage'):
            return 'payment_section_opened'
        if data.startswith('payment:buy:') or data.startswith('payment:plan:'):
            return 'payment_plan_clicked'
        if data.startswith('payment:pay:'):
            return 'payment_invoice_opened'
        if data.startswith('payment:check'):
            return 'payment_check_clicked'
        if data.startswith('payment:history'):
            return 'payment_history_opened'
        if data.startswith('plan:'):
            return f"content_plan_action_{data.split(':', 1)[1]}"
        return 'callback_clicked'
