from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from aiogram.types import CallbackQuery, Message, TelegramObject


def escape_html(text: str | None) -> str:
    return html.escape(text or '')


def truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_subscription_related_event(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = (event.text or '').strip()
        return text.lower().startswith('/start')
    if isinstance(event, CallbackQuery):
        return event.data in {'check_subscription', 'go:menu'}
    return False


def is_billing_exempt_event(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = (event.text or '').strip()
        return text in {
            'ℹ️ Помощь',
            '👤 Личный кабинет',
            '💳 Подписка',
            '⬅️ Назад',
        } or text.lower().startswith('/start')
    if isinstance(event, CallbackQuery):
        data = event.data or ''
        return data.startswith('payment:') or data.startswith('profile:') or data in {'go:menu', 'check_subscription'}
    return False


def format_dt_human(value: str | None) -> str:
    if not value:
        return '—'
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime('%d.%m.%Y %H:%M')
    except ValueError:
        return value


def bool_to_ru(value: bool) -> str:
    return 'Да' if value else 'Нет'
