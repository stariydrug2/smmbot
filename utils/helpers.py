from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import CallbackQuery, Message, TelegramObject


def escape_html(text: str | None) -> str:
    return html.escape(text or '')


def truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_username(username: str | None) -> str:
    return (username or '').strip().lstrip('@').lower()


def format_dt_human(value: str | None) -> str:
    if not value:
        return '—'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime('%d.%m.%Y %H:%M')
    except ValueError:
        return str(value)


def is_subscription_related_event(event: TelegramObject) -> bool:
    """Events required for channel-subscription gate."""
    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        return text.startswith('/start')
    if isinstance(event, CallbackQuery):
        return event.data == 'check_subscription'
    return False


def is_billing_exempt_event(event: TelegramObject) -> bool:
    """Events available even after paid access expires."""
    if isinstance(event, Message):
        text = (event.text or '').strip()
        lowered = text.lower()

        public_commands = (
            '/start',
            '/admin',
            '/help',
            '/grant_access',
            '/revoke_access',
            '/check_reminders',
        )
        if lowered.startswith(public_commands):
            return True

        public_buttons = {
            '👤 Личный кабинет',
            'ℹ️ Помощь',
            '🛠 Админка',
            '💳 Подписка',
            '⬅️ Назад',
        }
        return text in public_buttons

    if isinstance(event, CallbackQuery):
        data = event.data or ''
        allowed_exact = {'go:menu', 'check_subscription'}
        allowed_prefixes = (
            'payment:',
            'profile:',
        )
        return data in allowed_exact or data.startswith(allowed_prefixes)

    return False


def _normalize_bold_tags(raw: str) -> str:
    fixed = raw
    replacements = {
        '<b/3>': '</b>',
        '<b/>': '</b>',
        '<b />': '</b>',
        '</ b>': '</b>',
        '< /b>': '</b>',
        '<strong>': '<b>',
        '</strong>': '</b>',
    }
    for old, new in replacements.items():
        fixed = fixed.replace(old, new)
    fixed = re.sub(r'<\s*b\s*>', '<b>', fixed, flags=re.IGNORECASE)
    fixed = re.sub(r'<\s*/\s*b\s*>', '</b>', fixed, flags=re.IGNORECASE)
    return fixed


def render_model_text(text: str | None) -> str:
    """Render model output as Telegram-safe HTML.

    The bot uses parse_mode=HTML, so model markdown-like formatting is converted
    into real HTML. User/model raw HTML is escaped, except safe <b> tags.
    """
    raw = (text or '').strip()
    if not raw:
        return ''

    raw = _normalize_bold_tags(raw)

    converted_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            converted_lines.append('')
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            converted_lines.append(f"<b>{heading_match.group(2).strip(' :')}</b>")
            continue

        converted_lines.append(line)

    raw = '\n'.join(converted_lines)
    raw = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', raw, flags=re.DOTALL)

    escaped = html.escape(raw)
    # Allow only bold tags that were produced by the renderer/model.
    escaped = escaped.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    escaped = re.sub(r'\n{3,}', '\n\n', escaped)
    return escaped
