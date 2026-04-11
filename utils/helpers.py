from __future__ import annotations

import html
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
        return (event.text or '').strip().lower().startswith('/start')
    if isinstance(event, CallbackQuery):
        return event.data in {'check_subscription', 'go:menu'}
    return False
