from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from aiogram.types import CallbackQuery, Message, TelegramObject


_ALLOWED_HTML_TOKENS = {
    '<b>': '__TG_B_OPEN__',
    '</b>': '__TG_B_CLOSE__',
    '<strong>': '__TG_B_OPEN__',
    '</strong>': '__TG_B_CLOSE__',
    '<i>': '__TG_I_OPEN__',
    '</i>': '__TG_I_CLOSE__',
    '<em>': '__TG_I_OPEN__',
    '</em>': '__TG_I_CLOSE__',
    '<u>': '__TG_U_OPEN__',
    '</u>': '__TG_U_CLOSE__',
    '<s>': '__TG_S_OPEN__',
    '</s>': '__TG_S_CLOSE__',
    '<code>': '__TG_CODE_OPEN__',
    '</code>': '__TG_CODE_CLOSE__',
    '<pre>': '__TG_PRE_OPEN__',
    '</pre>': '__TG_PRE_CLOSE__',
}

_RESTORE_HTML_TOKENS = {
    '__TG_B_OPEN__': '<b>',
    '__TG_B_CLOSE__': '</b>',
    '__TG_I_OPEN__': '<i>',
    '__TG_I_CLOSE__': '</i>',
    '__TG_U_OPEN__': '<u>',
    '__TG_U_CLOSE__': '</u>',
    '__TG_S_OPEN__': '<s>',
    '__TG_S_CLOSE__': '</s>',
    '__TG_CODE_OPEN__': '<code>',
    '__TG_CODE_CLOSE__': '</code>',
    '__TG_PRE_OPEN__': '<pre>',
    '__TG_PRE_CLOSE__': '</pre>',
}


def escape_html(text: str | None) -> str:
    """Escape text for safe Telegram HTML output."""
    return html.escape(text or '')


def truncate(text: str, limit: int = 300) -> str:
    """Trim long text without cutting UI too aggressively."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def ensure_dir(path: Path) -> Path:
    """Create directory if it does not exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_username(username: str | None) -> str:
    """Normalize Telegram username for DB lookups and admin commands."""
    return (username or '').strip().lstrip('@').lower()


def is_subscription_related_event(event: TelegramObject) -> bool:
    """Events that must stay available before channel subscription is confirmed."""
    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        return text.startswith('/start')

    if isinstance(event, CallbackQuery):
        return (event.data or '') in {'check_subscription', 'go:menu'}

    return False


def is_billing_exempt_event(event: TelegramObject) -> bool:
    """Events available even when trial/subscription is expired."""
    if is_subscription_related_event(event):
        return True

    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        if text.startswith('/admin') or text.startswith('/grant_access') or text.startswith('/revoke_access'):
            return True
        if text.startswith('/users') or text.startswith('/broadcast') or text.startswith('/broadcast_to'):
            return True
        if text.startswith('/check_reminders'):
            return True

        exempt_messages = {
            '/start',
            'ℹ️ помощь',
            'помощь',
            '🧑‍💻 поддержка',
            'поддержка',
            '👤 личный кабинет',
            'личный кабинет',
            '💳 подписка',
            'подписка',
            '🕘 история',
            'история',
            '⬅️ назад',
        }
        return text in exempt_messages

    if isinstance(event, CallbackQuery):
        data = (event.data or '').strip().lower()
        exempt_prefixes = (
            'payment:',
            'payments:',
            'plan:',
            'billing:',
            'profile:',
            'history:',
        )
        exempt_exact = {
            'check_subscription',
            'go:menu',
        }
        return data in exempt_exact or data.startswith(exempt_prefixes)

    return False


def format_dt_human(value: str | None) -> str:
    """Format ISO datetime from SQLite/API into readable Russian UI format."""
    if not value:
        return '—'

    raw = str(value).strip()
    if not raw:
        return '—'

    normalized = raw.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return raw

    return dt.strftime('%d.%m.%Y %H:%M')


def _preserve_safe_html(raw: str) -> str:
    protected = raw
    for tag, token in _ALLOWED_HTML_TOKENS.items():
        protected = re.sub(re.escape(tag), token, protected, flags=re.IGNORECASE)

    escaped = escape_html(protected)

    for token, tag in _RESTORE_HTML_TOKENS.items():
        escaped = escaped.replace(token, tag)

    return escaped


def _bold_labels(line: str) -> str:
    if line.startswith('<'):
        return line

    label_match = re.match(
        r'^([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 ()/№+\-]{0,44}:)\s*(.+)$',
        line,
    )
    if not label_match:
        return line

    label = label_match.group(1)
    value = label_match.group(2)
    return f'<b>{label}</b> {value}'


def render_model_text(text: str | None) -> str:
    """Render model output as Telegram-safe HTML.

    Converts markdown-like formatting to Telegram HTML and prevents raw broken tags
    such as <b/3> from appearing in the chat.
    """
    raw = (text or '').strip()
    if not raw:
        return ''

    # Remove malformed tags that models sometimes invent.
    raw = re.sub(r'<\s*b\s*/\s*\d+\s*>', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*/\s*b\s*\d+\s*>', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*b\s*/\s*>', '', raw, flags=re.IGNORECASE)

    rendered = _preserve_safe_html(raw)

    # Markdown bold -> Telegram HTML bold.
    rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered, flags=re.DOTALL)
    rendered = re.sub(r'__(.+?)__', r'<b>\1</b>', rendered, flags=re.DOTALL)

    lines: list[str] = []
    for line in rendered.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append('')
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            heading = heading_match.group(2).strip(' :')
            lines.append(f'<b>{heading}</b>')
            continue

        if stripped.startswith(('- ', '— ', '– ', '* ')):
            bullet_text = stripped[2:].strip()
            lines.append(f'• {bullet_text}')
            continue

        if re.match(r'^(день\s+\d+|вариант\s+\d+|неделя\s+\d+|пост\s+\d+)$', stripped, flags=re.IGNORECASE):
            lines.append(f'<b>{stripped}</b>')
            continue

        lines.append(_bold_labels(stripped))

    result = '\n'.join(lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()
