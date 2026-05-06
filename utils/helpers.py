from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram.types import CallbackQuery, Message, TelegramObject

_B_OPEN = '%%KONTUR_B_OPEN%%'
_B_CLOSE = '%%KONTUR_B_CLOSE%%'


def escape_html(text: str | None) -> str:
    return html.escape(text or '')


def truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_dt_human(value: Any) -> str:
    """Return a compact human-readable date for profile/admin screens."""
    if not value:
        return '—'
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return str(value)
    return dt.strftime('%d.%m.%Y %H:%M')


def _protect_valid_bold_tags(text: str) -> str:
    text = re.sub(r'<\s*b\s*>', _B_OPEN, text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*b\s*>', _B_CLOSE, text, flags=re.IGNORECASE)
    return text


def _remove_malformed_bold_tags(text: str) -> str:
    # Модели иногда отдают мусор вроде <b/3>, </b/3>, <b/>.
    # Такие куски Telegram не понимает, поэтому убираем их до HTML-рендера.
    text = re.sub(r'<\s*/?\s*b\s*/\s*\d+\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*b\s*/\s*>', '', text, flags=re.IGNORECASE)
    return text


def render_model_text(text: str | None) -> str:
    """Convert model markdown-ish output to safe Telegram HTML.

    Keeps valid <b>...</b>, converts # headings and **bold** into HTML,
    escapes everything else, and removes broken pseudo-tags like <b/3>.
    """
    if not text:
        return ''

    raw = _remove_malformed_bold_tags(str(text))
    raw = _protect_valid_bold_tags(raw)
    escaped = html.escape(raw)
    escaped = escaped.replace(html.escape(_B_OPEN), '<b>').replace(html.escape(_B_CLOSE), '</b>')

    lines: list[str] = []
    for line in escaped.splitlines():
        stripped = line.strip()
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            lines.append(f'<b>{heading_match.group(2).strip()}</b>')
            continue
        # Частые markdown-маркеры списков от моделей.
        line = re.sub(r'^\s*[-*]\s+\*\*(.+?)\*\*\s*:', r'• <b>\1:</b>', line)
        line = re.sub(r'^\s*[-*]\s+(.+?):\s*$', r'• <b>\1:</b>', line)
        lines.append(line)

    rendered = '\n'.join(lines)
    rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered, flags=re.DOTALL)
    rendered = re.sub(r'(?m)^([А-ЯA-ZЁ][^\n:]{2,60}:)\s*$', r'<b>\1</b>', rendered)
    return rendered


def is_subscription_related_event(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        return text.startswith('/start')
    if isinstance(event, CallbackQuery):
        return event.data in {'check_subscription', 'go:menu'}
    return False


def is_billing_exempt_event(event: TelegramObject) -> bool:
    """Events allowed even when paid subscription/trial is expired."""
    allowed_texts = {
        '💳 Подписка',
        '👤 Личный кабинет',
        '🕘 История',
        'ℹ️ Помощь',
        '🧑\u200d💻 Поддержка',
        '🧑‍💻 Поддержка',
        '⬅️ Назад',
        '🛠 Админка',
    }
    allowed_commands = (
        '/start',
        '/admin',
        '/grant_access',
        '/revoke_access',
        '/check_reminders',
        '/broadcast',
        '/broadcast_to',
        '/users',
    )

    if isinstance(event, Message):
        text = (event.text or '').strip()
        lowered = text.lower()
        if text in allowed_texts:
            return True
        if any(lowered.startswith(cmd) for cmd in allowed_commands):
            return True
        return False

    if isinstance(event, CallbackQuery):
        data = event.data or ''
        if data in {'go:menu', 'check_subscription'}:
            return True
        return data.startswith(('pay:', 'payment:', 'payments:', 'profile:', 'history:'))

    return False
