from __future__ import annotations

import html
import re
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


def render_model_text(text: str | None) -> str:
    """
    Converts model output into Telegram-safe HTML.

    Rules:
    - escape raw HTML first
    - convert markdown headings into bold lines
    - convert **bold** fragments into <b>...</b>
    - normalize bullet points a bit
    """
    raw = (text or '').strip()
    if not raw:
        return ''

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

        # Preserve common bullet markers
        if stripped.startswith(('- ', '— ', '– ', '* ')):
            bullet_text = stripped[2:].strip()
            lines.append(f'• {bullet_text}')
            continue

        lines.append(line)

    rendered = '\n'.join(lines)

    # Convert markdown bold to HTML bold after escaping.
    rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered, flags=re.DOTALL)

    # Collapse excessive empty lines a little.
    rendered = re.sub(r'\n{3,}', '\n\n', rendered)
    return rendered
