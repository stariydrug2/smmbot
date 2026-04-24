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


def is_subscription_related_event(event: TelegramObject) -> bool:
    """Allow onboarding and channel-subscription checks before billing checks."""
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
        exempt_messages = {
            '/start',
            'ℹ️ помощь',
            'помощь',
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
    """Convert model output to Telegram-safe HTML.

    What it does:
    - preserves a tiny safe subset of HTML tags that the model may already output
    - converts markdown headings to bold lines
    - converts **bold** fragments to <b>...</b>
    - bolds common label prefixes like `Тема:`
    - normalizes bullets
    - removes malformed pseudo-tags like `<b/3>`
    """
    raw = (text or '').strip()
    if not raw:
        return ''

    # Normalize a few malformed variants the model sometimes invents.
    raw = re.sub(r'<\s*b\s*/\s*\d+\s*>', '</b>', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*/\s*b\s*\d*\s*>', '</b>', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*b\s*>', '<b>', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*/\s*b\s*>', '</b>', raw, flags=re.IGNORECASE)

    placeholders = {
        '<b>': '__TG_B_OPEN__',
        '</b>': '__TG_B_CLOSE__',
        '<i>': '__TG_I_OPEN__',
        '</i>': '__TG_I_CLOSE__',
        '<u>': '__TG_U_OPEN__',
        '</u>': '__TG_U_CLOSE__',
        '<code>': '__TG_CODE_OPEN__',
        '</code>': '__TG_CODE_CLOSE__',
        '<pre>': '__TG_PRE_OPEN__',
        '</pre>': '__TG_PRE_CLOSE__',
    }

    preserved = raw
    for tag, token in placeholders.items():
        preserved = preserved.replace(tag, token)

    escaped = escape_html(preserved)
    for tag, token in placeholders.items():
        escaped = escaped.replace(token, tag)

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

        if not stripped.startswith('<'):
            label_match = re.match(r'^([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 ()/+-]{0,40}:)\s*(.+)$', stripped)
            if label_match:
                label = label_match.group(1)
                value = label_match.group(2)
                lines.append(f'<b>{label}</b> {value}')
                continue

            if re.match(r'^(день\s+\d+|вариант\s+\d+|неделя\s+\d+)$', stripped, flags=re.IGNORECASE):
                lines.append(f'<b>{stripped}</b>')
                continue

        lines.append(line)

    rendered = '\n'.join(lines)
    rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered, flags=re.DOTALL)
    rendered = re.sub(r'__(.+?)__', r'<b>\1</b>', rendered, flags=re.DOTALL)
    rendered = re.sub(r'\n{3,}', '\n\n', rendered)
    return rendered
