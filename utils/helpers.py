from __future__ import annotations

import html
import re
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


def normalize_username(username: str | None) -> str:
    return (username or '').strip().lstrip('@').lower()


def is_subscription_related_event(event: TelegramObject) -> bool:
    """Allow channel-subscription and start checks before billing checks."""
    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        return text.startswith('/start')
    if isinstance(event, CallbackQuery):
        return (event.data or '') in {'check_subscription', 'go:menu'}
    return False


def is_billing_exempt_event(event: TelegramObject) -> bool:
    """Events that must stay available even when paid access is expired."""
    if is_subscription_related_event(event):
        return True

    if isinstance(event, Message):
        text = (event.text or '').strip().lower()
        if text.startswith(('/admin', '/grant_access', '/revoke_access', '/check_reminders')):
            return True
        exempt_messages = {
            'ℹ️ помощь',
            'помощь',
            '👤 личный кабинет',
            'личный кабинет',
            '💳 подписка',
            'подписка',
            '⬅️ назад',
        }
        return text in exempt_messages

    if isinstance(event, CallbackQuery):
        data = (event.data or '').strip().lower()
        exempt_prefixes = (
            'payment:',
            'payments:',
            'billing:',
            'profile:',
        )
        exempt_exact = {
            'check_subscription',
            'go:menu',
        }
        return data in exempt_exact or data.startswith(exempt_prefixes)

    return False


def format_dt_human(value: str | None) -> str:
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


def render_model_text(text: str | None) -> str:
    """Convert LLM output into Telegram-safe HTML.

    The bot uses parse_mode=HTML. This function escapes user/model text first,
    then allows only our own safe <b> tags.
    """
    raw = (text or '').strip()
    if not raw:
        return ''

    # Remove broken literal pseudo-tags before escaping: <b/3>, <b/>, etc.
    raw = re.sub(r'</?b[^>]*?>', '', raw, flags=re.IGNORECASE)

    escaped = escape_html(raw)
    lines: list[str] = []

    for line in escaped.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append('')
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            content = heading_match.group(2).strip(' :')
            lines.append(f'<b>{content}</b>')
            continue

        if stripped.startswith(('- ', '— ', '– ', '* ')):
            bullet_text = stripped[2:].strip()
            lines.append(f'• {bullet_text}')
            continue

        # Bold short labels like "Тема:", "Цель:", "День 1:" at line start.
        label_match = re.match(r'^([А-ЯA-ZЁ0-9][^:\n]{1,45}:)\s*(.*)$', stripped)
        if label_match:
            label, rest = label_match.groups()
            if len(label.split()) <= 6:
                lines.append(f'<b>{label}</b> {rest}'.rstrip())
                continue

        lines.append(line)

    rendered = '\n'.join(lines)
    rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered, flags=re.DOTALL)
    rendered = re.sub(r'\*(.+?)\*', r'<b>\1</b>', rendered)
    rendered = re.sub(r'\n{3,}', '\n\n', rendered)
    return rendered
